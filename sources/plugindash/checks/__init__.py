"""Check loader.

A check is a Python module with:

    ID = "my_check"            # short, unique, lower-case
    TITLE = "What it checks"
    DESCRIPTION = "One sentence shown on the dashboard's About panel."

    def run(repo, plugin, ctx):
        # repo:   a RepoView (see sources/base.py)
        # plugin: dict of $plugin fields from version.php on the default branch
        # ctx:    Context (config, current time, latest Moodle branch, directory client)
        return [Finding(ID, AMBER, "Something needs attention", url)]

Built-in checks live in this folder. Your own checks go in the extensions
folder (default /home/yunohost.app/plugindash/extensions/checks/) and are
picked up on the next run. A file there with the same ID as a built-in check
replaces it.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import pkgutil
from dataclasses import dataclass, field
from datetime import datetime
from types import ModuleType
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class Context:
    cfg: dict[str, Any]
    now: datetime
    moodle_latest: int = 0
    directory: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


def fix_for(module: ModuleType, message: str) -> str | None:
    """The check's advice for a finding: the first key of its FIX table found in the message, else the "" entry."""
    table = getattr(module, "FIX", None)
    if not isinstance(table, dict):
        return None
    for key, text in table.items():
        if key and key in message:
            return text
    return table.get("")


def _valid(module: ModuleType) -> bool:
    return all(hasattr(module, attr) for attr in ("ID", "TITLE", "run")) and callable(module.run)


def load_checks(extensions_dir: str | None = None) -> list[ModuleType]:
    found: dict[str, ModuleType] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        if _valid(module):
            found[module.ID] = module
    if extensions_dir:
        folder = os.path.join(extensions_dir, "checks")
        if os.path.isdir(folder):
            for filename in sorted(os.listdir(folder)):
                if not filename.endswith(".py") or filename.startswith("_"):
                    continue
                path = os.path.join(folder, filename)
                try:
                    spec = importlib.util.spec_from_file_location(f"plugindash_ext_{filename[:-3]}", path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                except Exception as err:  # A broken extension must not stop the run.
                    log.error("Could not load extension check %s: %s", path, err)
                    continue
                if _valid(module):
                    found[module.ID] = module
                else:
                    log.error("Extension %s is missing ID, TITLE or run()", path)
    return sorted(found.values(), key=lambda m: (getattr(m, "ORDER", 50), m.ID))
