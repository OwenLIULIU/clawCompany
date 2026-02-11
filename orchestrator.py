"""
CEO Assistant Orchestrator.
The core coordination loop that drives multi-role collaboration.

The orchestrator:
1. Receives a task from the CEO (user)
2. Asks the CEO Assistant agent to analyze and decide next steps
3. Executes those steps by invoking the appropriate RoleEngines
4. Posts all interactions to the Feishu group as the respective bots
5. Loops until the CEO Assistant decides the task is complete
"""

import json
import logging
import asyncio
from datetime import datetime
from typing import Optional

from roles.registry import RoleConfig, ROLE_REGISTRY, get_ceo_assistant
from roles.engine import get_engine
from feishu.api import send_message_as_role
from gateway.session import run_openclaw_session
from config import (
    ROLE_CEO_ASSISTANT, ROLE_CTO, ROLE_PM, ROLE_DEV, ROLE_QA, ROLE_OPS,
    ROLE_DISPLAY_NAMES, ROLE_EMOJIS,
)

logger = logging.getLogger(__name__)

# Max orchestration rounds to prevent infinite loops
MAX_ROUNDS = 20


async def run_orchestration(
    task_description: str,
    sender_id: str,
    chat_id: str,
    task_id: str,
) -> None:
    """
    Main orchestration loop.

    The CEO Assistant analyzes the task, decides which role to engage,
    invokes that role, collects the result, then decides the next step.
    """
    assistant = get_ceo_assistant()
    if not assistant:
        logger.error("CEO Assistant role not configured")
        return

    # Acknowledge receipt
    await send_message_as_role(
        app_id=assistant.app_id,
        app_secret=assistant.app_secret,
        chat_id=chat_id,
        text=f"{assistant.emoji} 收到任务，正在分析并安排团队协作...",
    )

    # Build the available roles description for the orchestrator
    available_roles = _build_available_roles_description()

    # Orchestrator session - persists across the full task lifecycle
    orch_session_key = f"feishu:role:ceo_assistant:orchestrate:{task_id}"

    # Initial orchestrator prompt
    orchestrator_system = (
        f"You are CEO助理 at ClawCompany. Your job is to coordinate a team to complete a task.\n"
        f"{assistant.system_prompt}\n\n"
        f"[AVAILABLE TEAM MEMBERS]\n{available_roles}\n\n"
        f"[COORDINATION RULES]\n"
        f"1. Analyze the task and decide which team member should work on it next.\n"
        f"2. You must respond with a JSON action. Two possible actions:\n"
        f"   a) DELEGATE: assign work to a team member\n"
        f"      {{\"action\": \"delegate\", \"role\": \"<role_id>\", \"instruction\": \"<specific instruction for that role>\"}}\n"
        f"   b) COMPLETE: task is done, deliver final result to CEO\n"
        f"      {{\"action\": \"complete\", \"summary\": \"<final report to CEO>\"}}\n"
        f"3. The 'instruction' should be clear and specific. Include references to files or prior results.\n"
        f"4. You can only delegate to ONE role at a time.\n"
        f"5. After receiving a role's output, decide the next step.\n"
        f"6. Keep group messages SHORT and natural, like a real team lead.\n"
        f"7. ALWAYS respond with valid JSON, nothing else.\n\n"
        f"[TASK FROM CEO]\n{task_description}"
    )

    # Conversation history for the orchestrator
    conversation_context = orchestrator_system
    round_count = 0

    while round_count < MAX_ROUNDS:
        round_count += 1
        logger.info(f"[Orchestrator] Round {round_count}/{MAX_ROUNDS} for task {task_id}")

        # Ask CEO Assistant to make a decision
        decision_text = await _call_orchestrator(orch_session_key, conversation_context)

        if not decision_text:
            await send_message_as_role(
                app_id=assistant.app_id,
                app_secret=assistant.app_secret,
                chat_id=chat_id,
                text=f"{assistant.emoji} ⚠️ 协调过程遇到问题，请稍后重试。",
            )
            return

        # Parse the decision
        action = _parse_action(decision_text)

        if not action:
            logger.warning(f"[Orchestrator] Failed to parse action: {decision_text[:200]}")
            # Feed back the error and ask for a valid response
            conversation_context = (
                f"Your previous response was not valid JSON. Please respond with exactly one JSON object:\n"
                f"Either: {{\"action\": \"delegate\", \"role\": \"<role_id>\", \"instruction\": \"...\"}}\n"
                f"Or: {{\"action\": \"complete\", \"summary\": \"...\"}}\n"
                f"Your previous response was: {decision_text[:300]}"
            )
            continue

        # Handle COMPLETE action
        if action.get("action") == "complete":
            summary = action.get("summary", "任务已完成。")
            await send_message_as_role(
                app_id=assistant.app_id,
                app_secret=assistant.app_secret,
                chat_id=chat_id,
                text=f"{assistant.emoji} 任务完成！\n\n{summary}",
            )
            logger.info(f"[Orchestrator] Task {task_id} completed in {round_count} rounds")
            return

        # Handle DELEGATE action
        if action.get("action") == "delegate":
            target_role_id = action.get("role", "")
            instruction = action.get("instruction", "")

            if target_role_id not in ROLE_REGISTRY:
                conversation_context = (
                    f"Invalid role_id '{target_role_id}'. "
                    f"Valid roles: {', '.join(ROLE_REGISTRY.keys())}. "
                    f"Please try again."
                )
                continue

            target_role = ROLE_REGISTRY[target_role_id]
            target_name = target_role.display_name

            # Post delegation message in group as CEO Assistant
            await send_message_as_role(
                app_id=assistant.app_id,
                app_secret=assistant.app_secret,
                chat_id=chat_id,
                text=f"{assistant.emoji} @{target_name} {instruction}",
            )

            # Execute the role's task
            engine = get_engine(target_role_id)
            if not engine:
                conversation_context = (
                    f"Failed to get engine for role '{target_role_id}'. "
                    f"Please choose another role."
                )
                continue

            role_result = await engine.execute_task(
                task_description=instruction,
                task_id=task_id,
                chat_id=chat_id,
            )

            # Feed the result back to the orchestrator for next decision
            result_summary = role_result if role_result else "(No output from this role)"
            conversation_context = (
                f"[RESULT FROM {target_name}]\n"
                f"{result_summary}\n\n"
                f"Based on this result, decide the next step. "
                f"Respond with a JSON action (delegate or complete)."
            )

    # Max rounds reached
    await send_message_as_role(
        app_id=assistant.app_id,
        app_secret=assistant.app_secret,
        chat_id=chat_id,
        text=f"{assistant.emoji} ⚠️ 协调已达到最大轮次({MAX_ROUNDS})，任务暂停。请检查进度。",
    )


async def _call_orchestrator(session_key: str, message: str) -> Optional[str]:
    """Call the CEO Assistant agent session and collect its response."""
    response_parts = []

    async def on_text(delta: str):
        response_parts.append(delta)

    result = await run_openclaw_session(
        session_key=session_key,
        initial_message=message,
        on_text=on_text,
    )

    return "".join(response_parts).strip() if response_parts else result


def _build_available_roles_description() -> str:
    """Build a description of all available roles for the orchestrator prompt."""
    lines = []
    for role_id, config in ROLE_REGISTRY.items():
        if role_id == ROLE_CEO_ASSISTANT:
            continue  # Don't list itself
        lines.append(f"- role_id: \"{role_id}\" | name: {config.display_name} {config.emoji}")
    return "\n".join(lines)


def _parse_action(text: str) -> Optional[dict]:
    """
    Parse a JSON action from the orchestrator's response.
    Handles cases where JSON is embedded in markdown code blocks.
    """
    import re

    # Try direct JSON parse
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding JSON-like structure in the text
    match = re.search(r"\{[^{}]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None
