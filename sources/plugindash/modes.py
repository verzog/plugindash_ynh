"""Licence modes, from the Moodle plugin conventions: they decide which rules a plugin is held to.

A  In-house SCCA plugin: proprietary, never distributed (no release zip or directory listing needed,
   and the repository must stay private).
B  GPLv3+ plugin, distributed (verzog or EduCheckout): the full release rules apply.

The mode is read from the @license tag in version.php, which is the plugin's source of truth.
"""

from __future__ import annotations

from typing import Any

MODE_A = "A"
MODE_B = "B"
MODE_OTHER = "other"


def plugin_mode(plugin: dict[str, Any]) -> str:
    tag = (plugin.get("license") or "").lower()
    if "skin cancer college" in tag or "scca" in tag:
        return MODE_A
    if "affero" in tag or "agpl" in tag:
        return MODE_OTHER
    if "gpl" in tag or "general public license" in tag:
        return MODE_B
    return MODE_OTHER


def mode_label(plugin: dict[str, Any]) -> str:
    """Short tag shown on the dashboard."""
    mode = plugin_mode(plugin)
    if mode == MODE_A:
        return "SCCA"
    if mode == MODE_B:
        return "GPL"
    tag = (plugin.get("license") or "").lower()
    if not tag:
        return "No licence"
    if "proprietary" in tag or "all rights reserved" in tag:
        return "Proprietary"
    return "Other licence"
