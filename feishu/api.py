"""
Feishu API Helpers.
Token management and message sending for multiple bot roles.
"""

import os
import re
import json
import time
import logging
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# ============ Token Cache (per app_id) ============

_token_cache: Dict[str, Dict] = {}
# Structure: { app_id: {"token": str, "expires_at": float} }


async def get_tenant_token(app_id: str, app_secret: str) -> str:
    """
    Get Feishu tenant access token for a specific app. Results are cached.
    """
    now = time.time()
    cached = _token_cache.get(app_id)
    if cached and cached["token"] and cached["expires_at"] > now + 60:
        return cached["token"]

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            data = resp.json()
            if data.get("code") == 0:
                token = data.get("tenant_access_token", "")
                expire = data.get("expire", 7200)
                _token_cache[app_id] = {"token": token, "expires_at": now + expire}
                logger.info(f"Refreshed tenant token for app {app_id[:8]}...")
                return token
            else:
                logger.error(f"Failed to get token for app {app_id[:8]}...: {data}")
                return ""
    except Exception as e:
        logger.error(f"Error getting token for app {app_id[:8]}...: {e}")
        return ""


async def send_message_as_role(
    app_id: str,
    app_secret: str,
    chat_id: str,
    text: str,
) -> bool:
    """
    Send a message to a Feishu group chat as a specific role's bot.
    Uses the Feishu IM API (not webhook).

    Supports plain text and rich text with @mentions.
    """
    token = await get_tenant_token(app_id, app_secret)
    if not token:
        logger.error(f"Cannot send: no token for app {app_id[:8]}...")
        return False

    # Detect <at> tags for rich text conversion
    at_match = re.match(r'^<at user_id="([^"]+)"></at>\n?(.*)', text, re.DOTALL)

    if at_match:
        user_id = at_match.group(1)
        content_text = at_match.group(2) or ""
        msg_type = "post"
        content = json.dumps({
            "zh_cn": {
                "title": "",
                "content": [[
                    {"tag": "at", "user_id": user_id},
                    {"tag": "text", "text": " " + content_text},
                ]],
            }
        })
    else:
        msg_type = "text"
        content = json.dumps({"text": text})

    async with httpx.AsyncClient() as client:
        for attempt in range(3):
            try:
                resp = await client.post(
                    "https://open.feishu.cn/open-apis/im/v1/messages",
                    params={"receive_id_type": "chat_id"},
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "receive_id": chat_id,
                        "msg_type": msg_type,
                        "content": content,
                    },
                )
                data = resp.json()
                if data.get("code") == 0:
                    return True
                else:
                    logger.warning(
                        f"Send failed (attempt {attempt + 1}/3, app {app_id[:8]}...): "
                        f"{json.dumps(data, ensure_ascii=False)[:200]}"
                    )
                    if attempt < 2:
                        import asyncio
                        await asyncio.sleep(1 * (attempt + 1))
            except Exception as e:
                logger.error(f"Send error (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    import asyncio
                    await asyncio.sleep(1)
    return False


async def download_feishu_image(
    app_id: str, app_secret: str,
    message_id: str, image_key: str, filename: str,
    workspace_dir: str = "/workspace",
) -> str:
    """Download image from Feishu and save to workspace."""
    token = await get_tenant_token(app_id, app_secret)
    if not token:
        return ""

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{image_key}",
                headers={"Authorization": f"Bearer {token}"},
                params={"type": "image"},
            )
            if resp.status_code == 200:
                os.makedirs(workspace_dir, exist_ok=True)
                filepath = os.path.join(workspace_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(resp.content)
                logger.info(f"Downloaded image to {filepath}")
                return filepath
            else:
                logger.error(f"Image download failed: {resp.status_code}")
                return ""
    except Exception as e:
        logger.error(f"Image download error: {e}")
        return ""


async def download_feishu_file(
    app_id: str, app_secret: str,
    message_id: str, file_key: str, filename: str,
    workspace_dir: str = "/workspace",
) -> str:
    """Download file from Feishu and save to workspace."""
    token = await get_tenant_token(app_id, app_secret)
    if not token:
        return ""

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{file_key}",
                headers={"Authorization": f"Bearer {token}"},
                params={"type": "file"},
            )
            if resp.status_code == 200:
                os.makedirs(workspace_dir, exist_ok=True)
                filepath = os.path.join(workspace_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(resp.content)
                logger.info(f"Downloaded file to {filepath}")
                return filepath
            else:
                logger.error(f"File download failed: {resp.status_code}")
                return ""
    except Exception as e:
        logger.error(f"File download error: {e}")
        return ""
