"""Load and validate config/sources.yaml at startup; a bad provider name is a startup crash, not a 3am surprise."""
from __future__ import annotations

import yaml

from fa.core.settings import CONFIG_DIR
from fa.registry.spec import Registry


def load_registry() -> Registry:
    with open(CONFIG_DIR / "sources.yaml", "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    reg = Registry.model_validate(raw)
    for need, route in reg.routes.items():
        for b in route.base + route.overlay:
            if b.provider not in reg.providers:
                raise ValueError(f"sources.yaml: route '{need}' references unknown provider '{b.provider}'")
    return reg
