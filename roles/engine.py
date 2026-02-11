"""
Role Engine.
Handles message processing for individual roles, including
direct Q&A mode and task execution mode.
"""

import logging
from typing import Optional

from roles.registry import RoleConfig, ROLE_REGISTRY
from feishu.api import send_message_as_role
from gateway.session import run_openclaw_session
from config import ROLE_DISPLAY_NAMES

logger = logging.getLogger(__name__)


class RoleEngine:
    """
    Processes messages directed at a specific role.

    Two modes:
    - Direct chat: User @s a role directly, the role answers independently.
    - Task execution: Orchestrator invokes a role to do a specific piece of work.
    """

    def __init__(self, config: RoleConfig):
        self.config = config

    async def handle_direct_chat(
        self, message: str, sender_id: str, chat_id: str
    ) -> None:
        """
        Handle a direct @mention from a user to this role.
        The role answers independently without going through the orchestrator.
        """
        session_key = f"feishu:role:{self.config.role_id}:chat:{chat_id}"

        # Build the augmented message with role identity
        augmented = self._build_direct_prompt(message)

        # Collect response chunks for batched sending
        response_parts = []

        async def on_text(delta: str):
            response_parts.append(delta)

        async def on_tool(tool_name: str, args: dict):
            # Optionally send tool feedback (keep minimal)
            pass

        result = await run_openclaw_session(
            session_key=session_key,
            initial_message=augmented,
            on_text=on_text,
            on_tool_use=on_tool,
        )

        # Send the complete response as this role's bot
        full_response = "".join(response_parts).strip()
        if full_response:
            await send_message_as_role(
                app_id=self.config.app_id,
                app_secret=self.config.app_secret,
                chat_id=chat_id,
                text=f"{self.config.emoji} {full_response}",
            )
        else:
            await send_message_as_role(
                app_id=self.config.app_id,
                app_secret=self.config.app_secret,
                chat_id=chat_id,
                text=f"{self.config.emoji} 暂时无法处理，请稍后重试。",
            )

    async def execute_task(
        self, task_description: str, task_id: str, chat_id: str
    ) -> Optional[str]:
        """
        Execute a task assigned by the orchestrator.
        Returns the role's response text (for the orchestrator to evaluate).

        The role also posts its response to the group chat as its own bot.
        """
        session_key = f"feishu:role:{self.config.role_id}:task:{task_id}"

        # Build the task prompt with role identity and constraints
        augmented = self._build_task_prompt(task_description)

        response_parts = []

        async def on_text(delta: str):
            response_parts.append(delta)

        async def on_tool(tool_name: str, args: dict):
            # Send brief tool feedback in group
            tool_desc = self._describe_tool(tool_name, args)
            if tool_desc:
                await send_message_as_role(
                    app_id=self.config.app_id,
                    app_secret=self.config.app_secret,
                    chat_id=chat_id,
                    text=f"🔨 {tool_desc}",
                )

        result = await run_openclaw_session(
            session_key=session_key,
            initial_message=augmented,
            on_text=on_text,
            on_tool_use=on_tool,
        )

        full_response = "".join(response_parts).strip()

        # Post the result to the group as this role
        if full_response:
            await send_message_as_role(
                app_id=self.config.app_id,
                app_secret=self.config.app_secret,
                chat_id=chat_id,
                text=f"{self.config.emoji} {full_response}",
            )

        return full_response or None

    def _build_direct_prompt(self, user_message: str) -> str:
        """Build prompt for direct chat mode."""
        # Build role awareness section
        other_roles = []
        for rid, rname in ROLE_DISPLAY_NAMES.items():
            if rid != self.config.role_id:
                other_roles.append(f"- @{rname}")

        roles_str = "\n".join(other_roles)
        return (
            f"[ROLE IDENTITY]\n"
            f"You are {self.config.display_name} at ClawCompany.\n"
            f"{self.config.system_prompt}\n\n"
            f"[COMMUNICATION STYLE]\n"
            f"- Reply concisely and clearly, like a real person in a work chat.\n"
            f"- Do NOT be verbose. Get to the point.\n"
            f"- If the question is outside your expertise, suggest the user ask the appropriate colleague:\n"
            f"{roles_str}\n\n"
            f"[USER MESSAGE]\n"
            f"{user_message}"
        )

    def _build_task_prompt(self, task_description: str) -> str:
        """Build prompt for task execution mode."""
        return (
            f"[ROLE IDENTITY]\n"
            f"You are {self.config.display_name} at ClawCompany.\n"
            f"{self.config.system_prompt}\n\n"
            f"[COMMUNICATION STYLE]\n"
            f"- Be concise and professional, like a real team member reporting work.\n"
            f"- Focus on deliverables and results.\n"
            f"- Do NOT repeat the task description back.\n"
            f"- Output key findings, decisions, or file paths clearly.\n\n"
            f"[TASK]\n"
            f"{task_description}"
        )

    @staticmethod
    def _describe_tool(tool_name: str, args: dict) -> str:
        """Generate a brief human-readable description of a tool use."""
        if tool_name in ("run_command", "exec"):
            cmd = args.get("command") or args.get("CommandLine") or ""
            return f"执行: {cmd[:40]}..." if len(cmd) > 40 else f"执行: {cmd}"
        elif tool_name in ("read_file", "view_file"):
            path = args.get("path") or args.get("AbsolutePath") or ""
            return f"读取: {path.split('/')[-1]}"
        elif tool_name in ("write_file", "write_to_file"):
            path = args.get("path") or args.get("TargetFile") or ""
            return f"写入: {path.split('/')[-1]}"
        return ""


# ============ Engine Registry ============

_engines: dict[str, RoleEngine] = {}


def get_engine(role_id: str) -> Optional[RoleEngine]:
    """Get or create a RoleEngine for the given role_id."""
    if role_id not in _engines:
        config = ROLE_REGISTRY.get(role_id)
        if not config:
            return None
        _engines[role_id] = RoleEngine(config)
    return _engines[role_id]


def get_engine_by_app_id(app_id: str) -> Optional[RoleEngine]:
    """Get the RoleEngine for a Feishu app_id."""
    from roles.registry import get_role_by_app_id
    role = get_role_by_app_id(app_id)
    if role:
        return get_engine(role.role_id)
    return None
