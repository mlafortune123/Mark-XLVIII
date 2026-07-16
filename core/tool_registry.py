"""
core/tool_registry.py — single-file-change tool registration.

Problem this replaces: adding one tool used to touch four places — an
import in main.py, an entry in TOOL_DECLARATIONS, an elif branch in
_dispatch_tool(), and a routing hint in core/prompt.txt.

Each migrated actions/*.py module declares its own `TOOLS: list[ToolSpec]`
next to its implementation. main.py imports those modules (for their
TOOLS list) and calls register() on each entry; TOOL_DECLARATIONS becomes
the not-yet-migrated static declarations + all_declarations(); routing
hints get assembled into the system prompt's TOOL ROUTING section instead
of being hand-edited into prompt.txt per tool.

Migration is incremental: the registry and the legacy elif chain in
_dispatch_tool() coexist. _dispatch_tool() checks the registry first,
falling through to the elif chain for anything not yet migrated.
core/tool_schema.py's Gemini→OpenAI conversion is unaffected — it already
just consumes whatever declarations list it's handed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class ToolContext:
    """Replaces the ad-hoc player=/speak=/response= kwargs threaded through
    the legacy elif chain — room to grow (vault handle, session info)
    without touching every handler's signature again."""
    ui: object          # JarvisUI facade
    speak: Callable      # JarvisLive.speak


@dataclass
class ToolSpec:
    name: str
    declaration: dict
    handler: Callable[[dict, "ToolContext"], str]      # sync; dispatcher wraps in executor
    routing_hint: str | None = None
    blocking: bool = True                                # False → handler is already async


REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    REGISTRY[spec.name] = spec


def all_declarations() -> list[dict]:
    return [spec.declaration for spec in REGISTRY.values()]


def routing_block() -> str:
    hints = [spec.routing_hint for spec in REGISTRY.values() if spec.routing_hint]
    if not hints:
        return ""
    return "TOOL ROUTING (registry):\n" + "\n".join(hints)
