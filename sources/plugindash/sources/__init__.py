"""Repository sources. Each one turns a forge's API into RepoView objects."""

from __future__ import annotations

from typing import Any

from .base import RepoView, Source


def build_sources(cfg: dict[str, Any]) -> list[Source]:
    sources: list[Source] = []
    if cfg.get("github_enabled") and cfg.get("github_token"):
        from .github import GitHubSource
        sources.append(GitHubSource(cfg))
    if cfg.get("gitlab_enabled") and cfg.get("gitlab_url") and cfg.get("gitlab_token"):
        from .gitlab import GitLabSource
        sources.append(GitLabSource(cfg))
    return sources


__all__ = ["RepoView", "Source", "build_sources"]
