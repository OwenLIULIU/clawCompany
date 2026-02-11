"""
Connection Manager.
Manages active asyncio tasks for chat and background operations.
"""

import asyncio
import logging
from typing import Dict

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections to OpenClaw."""

    def __init__(self):
        # Chat tasks: One per session_id (Singleton per role+chat)
        self.active_chat_tasks: Dict[str, asyncio.Task] = {}

        # Background tasks: Multiple allowed (Parallel)
        self.active_background_tasks: Dict[str, asyncio.Task] = {}

    def register_chat_task(self, session_id: str, task: asyncio.Task):
        """Register a chat task, cancelling any existing one for this session."""
        if session_id in self.active_chat_tasks:
            old_task = self.active_chat_tasks[session_id]
            if not old_task.done():
                logger.info(f"Cancelling existing chat task for session {session_id}")
                old_task.cancel()

        self.active_chat_tasks[session_id] = task

        def _cleanup(t):
            if self.active_chat_tasks.get(session_id) == t:
                self.active_chat_tasks.pop(session_id, None)

        task.add_done_callback(_cleanup)

    def register_background_task(self, task_uuid: str, task: asyncio.Task):
        """Register a background task (no cancellation of others)."""
        self.active_background_tasks[task_uuid] = task
        task.add_done_callback(
            lambda t: self.active_background_tasks.pop(task_uuid, None)
        )


# Singleton
manager = ConnectionManager()
