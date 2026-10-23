"""Tiny HTTP client (standard library only) with retries and paging."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import __version__

USER_AGENT = f"plugindash/{__version__} (+YunoHost)"


class HttpError(Exception):
    def __init__(self, status: int, url: str, body: str = ""):
        self.status = status
        self.url = url
        self.body = body[:500]
        super().__init__(f"HTTP {status} for {redact_url(url)}")


class NotFound(HttpError):
    pass


class AuthError(HttpError):
    """401, or 403 that is not a rate limit."""


def redact_url(url: str) -> str:
    """Strip query strings (may hold tokens) from URLs shown in logs."""
    return url.split("?", 1)[0]


class Client:
    def __init__(self, base_url: str = "", headers: dict[str, str] | None = None,
                 timeout: int = 30, retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.headers = {"User-Agent": USER_AGENT}
        self.headers.update(headers or {})
        self.timeout = timeout
        self.retries = retries
        self.calls = 0

    def _url(self, path_or_url: str, params: dict[str, Any] | None = None) -> str:
        url = path_or_url if path_or_url.startswith("http") else f"{self.base_url}{path_or_url}"
        if params:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urllib.parse.urlencode(params)}"
        return url

    def request(self, method: str, path_or_url: str, params: dict[str, Any] | None = None,
                body: Any = None, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        url = self._url(path_or_url, params)
        data = None
        merged = dict(self.headers)
        merged.update(headers or {})
        if body is not None:
            if isinstance(body, (bytes, bytearray)):
                data = bytes(body)
            elif isinstance(body, str):
                data = body.encode("utf-8")
            else:
                data = json.dumps(body).encode("utf-8")
                merged.setdefault("Content-Type", "application/json")
        attempt = 0
        while True:
            attempt += 1
            self.calls += 1
            req = urllib.request.Request(url, data=data, method=method, headers=merged)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
            except urllib.error.HTTPError as err:
                text = err.read().decode("utf-8", "replace")
                hdrs = {k.lower(): v for k, v in (err.headers or {}).items()}
                if err.code == 404:
                    raise NotFound(404, url, text) from None
                rate_limited = err.code == 429 or (
                    err.code == 403 and (hdrs.get("x-ratelimit-remaining") == "0" or "rate limit" in text.lower())
                )
                if rate_limited and attempt <= self.retries:
                    reset = hdrs.get("retry-after") or ""
                    wait = int(reset) if reset.isdigit() else 30
                    time.sleep(min(wait, 120))
                    continue
                if err.code in (401, 403) and not rate_limited:
                    raise AuthError(err.code, url, text) from None
                if err.code >= 500 and attempt <= self.retries:
                    time.sleep(2 * attempt)
                    continue
                raise HttpError(err.code, url, text) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
                if attempt <= self.retries:
                    time.sleep(2 * attempt)
                    continue
                raise HttpError(0, url, str(err)) from None

    def get_json(self, path: str, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None) -> Any:
        _, _, raw = self.request("GET", path, params, headers=headers)
        return json.loads(raw.decode("utf-8")) if raw else None

    def get_text(self, path: str, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None) -> str:
        _, _, raw = self.request("GET", path, params, headers=headers)
        return raw.decode("utf-8", "replace")

    def get_paged(self, path: str, params: dict[str, Any] | None = None, item_key: str | None = None,
                  max_pages: int = 20) -> list[Any]:
        """Follow 'Link: rel=next' headers (GitHub and GitLab both send them)."""
        items: list[Any] = []
        url = self._url(path, params)
        for _ in range(max_pages):
            _, hdrs, raw = self.request("GET", url)
            data = json.loads(raw.decode("utf-8")) if raw else []
            page = data.get(item_key, []) if item_key and isinstance(data, dict) else data
            items.extend(page or [])
            match = re.search(r'<([^>]+)>;\s*rel="next"', hdrs.get("link", ""))
            if not match:
                break
            url = match.group(1)
        return items
