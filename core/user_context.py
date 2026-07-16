"""
core/user_context.py — one read-mostly accessor over the vault for
personalization data that used to be scattered across ad-hoc
get_identity_field()/get_settings() calls in main.py, proactive.py, and
actions/web_search.py.

Short TTL cache because this can be read once per tool call (e.g. every
web_search) without re-parsing the vault's Markdown notes each time.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from memory import vault_manager

_TTL_SECONDS = 60


@dataclass
class UserContext:
    name: str | None
    city: str | None                 # Identity city, falling back to weather_city
    language: str | None
    followed_topics: list[str] = field(default_factory=list)
    now: datetime = field(default_factory=datetime.now)


_cache: UserContext | None = None
_cache_at: float = 0.0


def _build() -> UserContext:
    name = vault_manager.get_identity_field("name") or None

    city = vault_manager.get_identity_field("city") or None
    if not city:
        city = (vault_manager.get_settings().get("weather_city") or "").strip() or None

    lang = vault_manager.get_identity_field("language") or None

    return UserContext(
        name=name,
        city=city,
        language=lang,
        followed_topics=vault_manager.list_followed_topics(),
        now=datetime.now(),
    )


def get_user_context(force_refresh: bool = False) -> UserContext:
    global _cache, _cache_at
    now = time.monotonic()
    if force_refresh or _cache is None or (now - _cache_at) > _TTL_SECONDS:
        _cache = _build()
        _cache_at = now
    return _cache
