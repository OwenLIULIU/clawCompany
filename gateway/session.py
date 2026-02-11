"""
OpenClaw Gateway Session Runner.
Connects via WebSocket to OpenClaw Gateway and runs agent sessions.
"""

import json
import uuid
import logging
import asyncio
from typing import Optional, Callable, Awaitable

import websockets

from config import OPENCLAW_GATEWAY_URL, OPENCLAW_TOKEN

logger = logging.getLogger(__name__)


async def run_openclaw_session(
    session_key: str,
    initial_message: str,
    on_text: Callable[[str], Awaitable[None]],
    on_tool_use: Optional[Callable[[str, dict], Awaitable[None]]] = None,
    timeout_seconds: float = 1800.0,
) -> Optional[str]:
    """
    Run a single OpenClaw agent session via WebSocket.

    This is a lower-level primitive. It connects, sends a message,
    collects the full response, and returns it.

    Args:
        session_key: Unique session namespace (e.g. "feishu:role:cto:task:xxx")
        initial_message: The message to send to the agent
        on_text: Async callback for streaming text chunks
        on_tool_use: Optional async callback for tool use events (tool_name, args)
        timeout_seconds: Max time to wait for a complete response

    Returns:
        The full accumulated response text, or None on failure.
    """
    gateway_ws = OPENCLAW_GATEWAY_URL.replace("http://", "ws://").replace("https://", "wss://")

    try:
        async with websockets.connect(gateway_ws, ping_interval=20, ping_timeout=20) as websocket:

            # 1. Handshake
            connect_req_id = str(uuid.uuid4())
            connect_payload = {
                "type": "req",
                "id": connect_req_id,
                "method": "connect",
                "params": {
                    "client": {
                        "id": "gateway-client",
                        "version": "1.0",
                        "mode": "backend",
                        "platform": "linux",
                    },
                    "auth": {"token": OPENCLAW_TOKEN},
                    "minProtocol": 3,
                    "maxProtocol": 3,
                },
            }
            await websocket.send(json.dumps(connect_payload))

            handshake_success = False
            for _ in range(10):
                msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                data = json.loads(msg)
                if (
                    data.get("type") == "res"
                    and data.get("id") == connect_req_id
                    and data.get("ok")
                ):
                    handshake_success = True
                    break

            if not handshake_success:
                logger.error(f"Handshake failed for session {session_key}")
                return None

            # 2. Send initial message
            req_id = str(uuid.uuid4())
            payload = {
                "type": "req",
                "id": req_id,
                "method": "chat.send",
                "params": {
                    "sessionKey": session_key,
                    "message": initial_message,
                    "idempotencyKey": str(uuid.uuid4()),
                },
            }
            await websocket.send(json.dumps(payload))

            # 3. Wait for chat.send response and capture runId
            run_id = None
            while True:
                try:
                    msg = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                except asyncio.TimeoutError:
                    logger.error(f"Timeout waiting for chat.send response: {session_key}")
                    return None

                data = json.loads(msg)

                # Look for the response to our chat.send request
                if (
                    data.get("type") == "res"
                    and data.get("id") == req_id
                ):
                    if data.get("ok"):
                        run_id = data.get("result", {}).get("runId")
                        logger.debug(f"Session {session_key} got runId={run_id}")
                    else:
                        logger.error(f"chat.send failed for {session_key}: {data}")
                        return None
                    break

            # 4. Event Loop - collect response, filtered by runId
            accumulated_response = ""

            while True:
                try:
                    msg = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
                except asyncio.TimeoutError:
                    logger.warning(f"Session {session_key} timed out")
                    break
                except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
                    logger.info(f"Session {session_key} connection closed")
                    break

                data = json.loads(msg)

                if data.get("type") == "event":
                    event_type = data.get("event")
                    event_payload = data.get("payload", {})
                    event_run = event_payload.get("run", "")

                    # Skip events from other runs
                    if run_id and event_run and event_run != run_id:
                        continue

                    # Tool use event
                    if (
                        event_type == "chat"
                        and event_payload.get("state") == "tool_use"
                        and on_tool_use
                    ):
                        tool_name = event_payload.get("tool", "")
                        tool_args = event_payload.get("args", {})
                        await on_tool_use(tool_name, tool_args)

                    # Assistant text stream
                    if (
                        event_type == "agent"
                        and event_payload.get("stream") == "assistant"
                    ):
                        data_node = event_payload.get("data", {})
                        # Gateway sends full accumulated text in each event, not deltas
                        text = data_node.get("text", "") or data_node.get("delta", "")
                        if text:
                            accumulated_response = text  # always keep latest full text
                            await on_text(text)

                    # Turn complete
                    if (
                        event_type == "chat"
                        and event_payload.get("state") == "final"
                    ):
                        # Check for non-streamed final message
                        final_msg = event_payload.get("message", {})
                        content = final_msg.get("content")
                        if isinstance(content, str) and content and not accumulated_response:
                            accumulated_response = content
                            await on_text(content)

                        logger.info(f"Session {session_key} turn complete")
                        break

            return accumulated_response if accumulated_response else None

    except Exception as e:
        logger.error(f"Session {session_key} error: {e}")
        return None
