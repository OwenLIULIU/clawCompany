"""
Bot Router.
Routes incoming Feishu webhook events to the correct RoleEngine.
"""

import logging
from typing import Optional

from roles.registry import get_role_by_app_id, RoleConfig
from config import ROLE_CEO_ASSISTANT

logger = logging.getLogger(__name__)


def identify_target_role(webhook_data: dict) -> Optional[RoleConfig]:
    """
    Determine which role should handle this webhook event.

    Strategy:
    1. Check header.app_id — Feishu sends events to the app whose bot was @mentioned
    2. This is the primary and most reliable routing mechanism

    Returns:
        RoleConfig if a matching role is found, None otherwise.
    """
    # Primary: route by app_id in the event header
    app_id = webhook_data.get("header", {}).get("app_id", "")
    if app_id:
        role = get_role_by_app_id(app_id)
        if role:
            logger.info(f"Routed to {role.emoji} {role.display_name} via app_id")
            return role
        else:
            logger.warning(f"Unknown app_id in webhook: {app_id}")
            return None

    logger.warning("No app_id found in webhook header")
    return None


def is_task_trigger(role: RoleConfig, message_text: str) -> bool:
    """
    Check if this message should trigger the orchestrator (task mode).

    Task mode is triggered when:
    - The message is directed at the CEO Assistant
    - The message contains a task-like instruction (not a simple question)

    For now, ANY message to CEO Assistant triggers orchestrator mode,
    unless it looks like a simple status query.
    """
    if role.role_id != ROLE_CEO_ASSISTANT:
        return False

    # Simple status queries go to direct chat
    status_keywords = ["进度", "状态", "进展", "汇报", "report", "status"]
    text_lower = message_text.lower().strip()
    for kw in status_keywords:
        if text_lower == kw or text_lower == f"查看{kw}":
            return False

    # Everything else to CEO Assistant is a task
    return True
