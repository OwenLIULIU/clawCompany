"""
Central configuration module.
Loads environment variables and builds role registry.
"""

import os
import logging
from typing import Dict

logger = logging.getLogger(__name__)

# ============ Shared Config ============

OPENCLAW_GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://host.docker.internal:18789")
OPENCLAW_TOKEN = os.environ.get("OPENCLAW_TOKEN", "")
WORKSPACE_DIR = "/workspace"

# ============ Role Definitions ============

# Role IDs (stable identifiers used throughout the system)
ROLE_CEO_ASSISTANT = "ceo_assistant"
ROLE_CTO = "cto"
ROLE_PM = "product_manager"
ROLE_DEV = "developer"
ROLE_QA = "tester"
ROLE_OPS = "ops_engineer"

ALL_ROLE_IDS = [ROLE_CEO_ASSISTANT, ROLE_CTO, ROLE_PM, ROLE_DEV, ROLE_QA, ROLE_OPS]

# Mapping from role_id to display name (used in group chat messages)
ROLE_DISPLAY_NAMES: Dict[str, str] = {
    ROLE_CEO_ASSISTANT: "CEO助理",
    ROLE_CTO: "CTO",
    ROLE_PM: "产品经理",
    ROLE_DEV: "开发工程师",
    ROLE_QA: "测试工程师",
    ROLE_OPS: "运维工程师",
}

# Mapping from role_id to emoji
ROLE_EMOJIS: Dict[str, str] = {
    ROLE_CEO_ASSISTANT: "📋",
    ROLE_CTO: "🏗️",
    ROLE_PM: "📝",
    ROLE_DEV: "💻",
    ROLE_QA: "🧪",
    ROLE_OPS: "🔧",
}

# Env var prefix mapping: role_id -> env var prefix
_ROLE_ENV_PREFIXES: Dict[str, str] = {
    ROLE_CEO_ASSISTANT: "ROLE_CEO_ASSISTANT",
    ROLE_CTO: "ROLE_CTO",
    ROLE_PM: "ROLE_PM",
    ROLE_DEV: "ROLE_DEV",
    ROLE_QA: "ROLE_QA",
    ROLE_OPS: "ROLE_OPS",
}


def load_role_credentials() -> Dict[str, Dict[str, str]]:
    """
    Load Feishu App credentials for each role from environment variables.

    Returns:
        Dict mapping role_id to {"app_id": ..., "app_secret": ...}
    """
    credentials: Dict[str, Dict[str, str]] = {}
    for role_id, prefix in _ROLE_ENV_PREFIXES.items():
        app_id = os.environ.get(f"{prefix}_APP_ID", "")
        app_secret = os.environ.get(f"{prefix}_APP_SECRET", "")
        if app_id and app_secret:
            credentials[role_id] = {
                "app_id": app_id,
                "app_secret": app_secret,
            }
            logger.info(f"Loaded credentials for role '{role_id}' (app_id: {app_id[:8]}...)")
        else:
            logger.warning(f"Missing credentials for role '{role_id}' ({prefix}_APP_ID / {prefix}_APP_SECRET)")
    return credentials
