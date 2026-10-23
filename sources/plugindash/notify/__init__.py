"""Alert channels.

A notifier is a module with:

    ID = "ntfy"
    def configured(cfg) -> bool
    def send(cfg, title, body, priority, url) -> None     # priority: "high" or "default"

Built-in: ntfy, email, Matrix. Extra channels go in
<extensions_dir>/notify/*.py and are loaded the same way as extra checks.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import pkgutil
from types import ModuleType
from typing import Any

log = logging.getLogger(__name__)


def load_notifiers(extensions_dir: str | None = None) -> list[ModuleType]:
    found: dict[str, ModuleType] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        found[module.ID] = module
    if extensions_dir:
        folder = os.path.join(extensions_dir, "notify")
        if os.path.isdir(folder):
            for filename in sorted(os.listdir(folder)):
                if not filename.endswith(".py") or filename.startswith("_"):
                    continue
                path = os.path.join(folder, filename)
                try:
                    spec = importlib.util.spec_from_file_location(f"plugindash_notify_{filename[:-3]}", path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    found[module.ID] = module
                except Exception as err:
                    log.error("Could not load extension notifier %s: %s", path, err)
    return list(found.values())


def send_all(cfg: dict[str, Any], title: str, body: str, priority: str = "default",
             url: str | None = None) -> dict[str, str]:
    """Send through every configured channel. Returns {channel: "sent" | error text}."""
    results = {}
    for notifier in load_notifiers(cfg.get("extensions_dir")):
        try:
            if not notifier.configured(cfg):
                continue
            notifier.send(cfg, title, body, priority, url)
            results[notifier.ID] = "sent"
        except Exception as err:  # One broken channel must not block the others.
            log.error("Alert via %s failed: %s", notifier.ID, err)
            results[notifier.ID] = f"failed: {err}"
    return results
