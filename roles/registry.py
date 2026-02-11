"""
Role Registry.
Defines RoleConfig and builds the registry from environment variables.
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import (
    ALL_ROLE_IDS,
    ROLE_DISPLAY_NAMES,
    ROLE_EMOJIS,
    ROLE_CEO_ASSISTANT,
    load_role_credentials,
)

logger = logging.getLogger(__name__)


@dataclass
class RoleConfig:
    """Configuration for a single bot role."""
    role_id: str
    display_name: str
    emoji: str
    app_id: str
    app_secret: str
    system_prompt: str = ""


# Global registry: app_id -> RoleConfig
APP_ID_TO_ROLE: Dict[str, RoleConfig] = {}

# Global registry: role_id -> RoleConfig
ROLE_REGISTRY: Dict[str, RoleConfig] = {}


def _load_system_prompt(role_id: str) -> str:
    """Load system prompt from roles/prompts/{role_id}.md"""
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts", f"{role_id}.md")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.warning(f"No prompt file found for role '{role_id}' at {prompt_path}")
        return f"You are {ROLE_DISPLAY_NAMES.get(role_id, role_id)}."


def build_registry() -> None:
    """
    Build the role registry from environment variables.
    Must be called at startup.
    """
    credentials = load_role_credentials()

    for role_id in ALL_ROLE_IDS:
        creds = credentials.get(role_id)
        if not creds:
            logger.warning(f"Skipping role '{role_id}': no credentials")
            continue

        config = RoleConfig(
            role_id=role_id,
            display_name=ROLE_DISPLAY_NAMES[role_id],
            emoji=ROLE_EMOJIS[role_id],
            app_id=creds["app_id"],
            app_secret=creds["app_secret"],
            system_prompt=_load_system_prompt(role_id),
        )

        ROLE_REGISTRY[role_id] = config
        APP_ID_TO_ROLE[creds["app_id"]] = config
        logger.info(
            f"Registered role: {config.emoji} {config.display_name} "
            f"(app_id={config.app_id[:8]}...)"
        )

    logger.info(f"Role registry built: {len(ROLE_REGISTRY)} roles active")


def get_role_by_app_id(app_id: str) -> Optional[RoleConfig]:
    """Look up a role by its Feishu app_id."""
    return APP_ID_TO_ROLE.get(app_id)


def get_role(role_id: str) -> Optional[RoleConfig]:
    """Look up a role by its role_id."""
    return ROLE_REGISTRY.get(role_id)


def get_ceo_assistant() -> Optional[RoleConfig]:
    """Get the CEO Assistant role config."""
    return ROLE_REGISTRY.get(ROLE_CEO_ASSISTANT)
