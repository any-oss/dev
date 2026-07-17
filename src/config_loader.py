from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from policy_gateway.config import Settings

CONFIG_FILES = (
    "layer_0_infra.json",
    "layer_1_data.json",
    "layer_2_logic.json",
    "layer_3_api.json",
    "layer_4_integration.json",
    "security.json",
)


def load_layer_config(config_dir: str | Path = "config") -> dict[str, Any]:
    """Load the Team-B-style JSON layer configuration bundle."""
    root = Path(config_dir)
    merged: dict[str, Any] = {}
    for filename in CONFIG_FILES:
        path = root / filename
        if not path.exists():
            raise FileNotFoundError(f"missing layer config: {path}")
        data = json.loads(path.read_text())
        if filename == "security.json":
            data = {key: value for key, value in data.items() if key != "security_headers"}
        merged.update(data)
    return merged


def settings_from_layers(config_dir: str | Path = "config") -> Settings:
    """Create validated application settings from layer JSON files."""
    return Settings(**load_layer_config(config_dir)).resolved()



def settings_from_environment() -> Settings:
    """Load Settings from PGW_CONFIG_DIR when set, otherwise from PGW_* env vars."""
    config_dir = os.getenv("PGW_CONFIG_DIR")
    if config_dir:
        return settings_from_layers(config_dir)
    return Settings().resolved()
