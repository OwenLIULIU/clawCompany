"""
Feishu Webhook Handler.
Receives Feishu webhook events and dispatches to the appropriate handler.
"""

import json
import logging
import asyncio
from datetime import datetime
from typing import Dict

from fastapi import Request

from router import identify_target_role, is_task_trigger
from roles.engine import get_engine
from orchestrator import run_orchestration
from gateway.connection import manager

logger = logging.getLogger(__name__)

# ============ Idempotency Cache ============

processed_events: Dict[str, datetime] = {}
EVENT_CACHE_TTL = 3600  # 1 hour


def _clean_event_cache():
    """Remove expired events from cache."""
    now = datetime.now()
    expired = [
        eid for eid, ts in processed_events.items()
        if (now - ts).total_seconds() > EVENT_CACHE_TTL
    ]
    for eid in expired:
        processed_events.pop(eid, None)


async def handle_webhook(request: Request) -> dict:
    """
    Main webhook handler for all Feishu bot events.

    All 6 bots share this single webhook endpoint.
    Routing is done by header.app_id.
    """
    # Parse request body
    try:
        raw_body = await request.body()
        data = json.loads(raw_body)
    except Exception as e:
        logger.error(f"JSON parse error: {e}")
        return {"error": "json parse error"}

    # Handle Feishu challenge verification
    if "challenge" in data:
        return {"challenge": data["challenge"]}

    # Idempotency check
    if "header" in data:
        event_id = data["header"].get("event_id")
        if event_id:
            if event_id in processed_events:
                logger.debug(f"Duplicate event {event_id} ignored")
                return {"status": "success"}
            processed_events[event_id] = datetime.now()
            if len(processed_events) > 1000:
                _clean_event_cache()

    # Only process message events
    if "header" not in data:
        return {"status": "skipped"}

    event_type = data["header"].get("event_type")
    if event_type != "im.message.receive_v1":
        logger.info(f"Ignoring event type: {event_type}")
        return {"status": "skipped"}

    # Route to the correct role
    role = identify_target_role(data)
    if not role:
        logger.warning("No matching role for this webhook event")
        return {"status": "no_role"}

    # Extract message details
    try:
        message = data["event"]["message"]
        msg_type = message.get("message_type", "text")
        chat_id = message.get("chat_id", "")
        message_id = message.get("message_id", "")

        # Extract sender info
        sender_data = data["event"]["sender"]["sender_id"]
        sender_id = (
            sender_data.get("user_id")
            or sender_data.get("open_id")
            or sender_data.get("union_id")
            or "unknown"
        )

        # Parse message content
        msg_content_str = message.get("content", "{}")
        msg_content = json.loads(msg_content_str) if isinstance(msg_content_str, str) else msg_content_str

        if msg_type != "text":
            # For now, only handle text messages
            logger.info(f"Ignoring non-text message type: {msg_type}")
            return {"status": "success"}

        text = msg_content.get("text", "").strip()
        if not text:
            return {"status": "success"}

        # Remove @bot mention prefix (Feishu adds @bot_name at the start)
        # The text may start with @BotName followed by the actual content
        clean_text = _strip_mention_prefix(text)
        if not clean_text:
            return {"status": "success"}

        logger.info(
            f"[{role.emoji} {role.display_name}] "
            f"Message from {sender_id} in {chat_id}: {clean_text[:100]}"
        )

        # Decide: orchestrator (task mode) or direct chat
        if is_task_trigger(role, clean_text):
            # Task mode: CEO Assistant orchestrates
            task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            task = asyncio.create_task(
                run_orchestration(
                    task_description=clean_text,
                    sender_id=sender_id,
                    chat_id=chat_id,
                    task_id=task_id,
                )
            )
            manager.register_background_task(task_id, task)
            logger.info(f"Started orchestration task {task_id}")
        else:
            # Direct chat: role answers independently
            engine = get_engine(role.role_id)
            if engine:
                session_id = f"{role.role_id}:{chat_id}"
                task = asyncio.create_task(
                    engine.handle_direct_chat(
                        message=clean_text,
                        sender_id=sender_id,
                        chat_id=chat_id,
                    )
                )
                manager.register_chat_task(session_id, task)

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Message handling error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"status": "error"}


def _strip_mention_prefix(text: str) -> str:
    """
    Strip the @BotName mention prefix from the message text.

    Feishu group messages that @mention a bot typically start with
    '@BotName ' followed by the actual message content.
    The text field may contain the raw mention as '@_user_1' or similar.
    """
    import re
    # Remove @_user_N patterns (Feishu internal mention format)
    cleaned = re.sub(r"@_user_\d+\s*", "", text).strip()
    # Remove @RoleName patterns (display name mentions)
    cleaned = re.sub(r"@\S+\s*", "", cleaned, count=1).strip()
    return cleaned if cleaned else text.strip()
