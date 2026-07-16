#web_search.py
from core.search_provider import backend_chain, DDGBackend, GeminiGroundedBackend, SearchResult, Source
from core.user_context import get_user_context


def _format_sources(sources: list[Source]) -> str:
    if not sources:
        return ""
    lines = ["\nSources:"]
    for i, s in enumerate(sources, 1):
        lines.append(f"{i}. {s.title} ({s.url})")
    return "\n".join(lines)


def _format_result(result: SearchResult) -> str:
    if not result.text:
        return ""
    return result.text + _format_sources(result.sources)


def _run_chain(query: str, *, extra_instruction: str = "", ddg_query: str | None = None,
               empty_message: str | None = None) -> str:
    """Walks backend_chain() in order, returning the first non-empty
    formatted result. This is what Part 1B's "modes become thin" collapses
    every mode down to — the enrichment (query text, extra_instruction) is
    the only per-mode logic left.

    `ddg_query` is the keyword-style form for DDG — the LLM-prose `query`
    ("Comprehensive, detailed explanation of: …") makes a poor keyword
    search, so modes that enrich the prose query should pass the plain one
    here too."""
    for backend in backend_chain():
        try:
            if isinstance(backend, DDGBackend):
                result = backend.search(ddg_query or query)
            else:
                result = backend.search(query, extra_instruction=extra_instruction)
            if result.text:
                return _format_result(result)
        except Exception as e:
            print(f"[WebSearch] ⚠️ {backend.name} failed ({e})")
    return empty_message or f"No results found for: {ddg_query or query}"


# ── Modes ──────────────────────────────────────────────────────────────────────

def _search(query: str) -> str:
    """Default search — Gemini grounded, DDG fallback."""
    return _run_chain(query)


def _news(query: str) -> str:
    """
    Primary backend with a bounded time budget; falls back to DDG news only
    on failure or timeout, rather than racing both backends on every call.
    """
    import concurrent.futures

    gemini_query = f"latest news today: {query}" if query else "top world news today"
    ddg_query    = query if query else "world news today"

    chain = backend_chain()
    primary = chain[0]
    try:
        if isinstance(primary, DDGBackend):
            result = primary.search(ddg_query, news=True)
        else:
            # No `with` block: ThreadPoolExecutor.__exit__ is shutdown(wait=True),
            # which blocks until the search call finishes and defeats the
            # timeout entirely. shutdown(wait=False) abandons the slow call
            # (its thread finishes in the background) so DDG can take over now.
            ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = ex.submit(primary.search, gemini_query)
            try:
                result = future.result(timeout=8.0)
            finally:
                ex.shutdown(wait=False)
        if result.text and len(result.text) > 60:
            return _format_result(result)
    except Exception as e:
        print(f"[WebSearch] ⚠️ {primary.name} news failed/timed out ({e})")

    try:
        fallback = DDGBackend()
        result = fallback.search(ddg_query, news=True, max_results=8)
        if result.text:
            return _format_result(result)
    except Exception as e:
        print(f"[WebSearch] ⚠️ DDG news fallback failed ({e})")

    return f"No news found for: {query}"


def _research(query: str) -> str:
    """Deep dive — asks the primary backend for a comprehensive answer with
    context; falls back down the chain."""
    research_query = (
        f"Comprehensive, detailed explanation of: {query}. "
        "Include background context, key facts, current state, and important nuances."
    )
    return _run_chain(research_query, ddg_query=query)


def _price(query: str) -> str:
    """Product price lookup — searches for current market prices."""
    price_query = f"current price of {query} — how much does it cost today"
    return _run_chain(price_query, ddg_query=f"{query} price buy")


def _events(query: str, city: str) -> str:
    """Local events / things-to-do — location-anchored via the resolved city."""
    ctx = get_user_context()
    city = (city or ctx.city or "").strip()
    if not city:
        return (
            "I don't know what city to search near — ask the user where, "
            "then call web_search again with mode='events' and a city."
        )

    events_query = f"Events in/near {city}: {query}. Include specific dates, venue names, and ticket/booking links."
    location_instruction = (
        f"The user is located in {city}; local time is {ctx.now.strftime('%A, %B %d, %Y %I:%M %p')}. "
        "\"This weekend\" / \"tonight\" resolve relative to that."
    )

    for backend in backend_chain():
        try:
            if isinstance(backend, DDGBackend):
                result = backend.search(f"{query} events {city} {ctx.now.strftime('%B %Y')}")
            else:
                result = backend.search(events_query, extra_instruction=location_instruction)
            if result.text:
                return _format_result(result)
        except Exception as e:
            print(f"[WebSearch] ⚠️ {backend.name} events failed ({e})")

    return f"No events found for {city}."


def _compare(items: list[str], aspect: str) -> str:
    query = (
        f"Compare {', '.join(items)} in terms of {aspect}. "
        "Give specific facts and data."
    )
    for backend in backend_chain():
        if isinstance(backend, DDGBackend):
            break
        try:
            result = backend.search(query)
            if result.text:
                return _format_result(result)
        except Exception as e:
            print(f"[WebSearch] ⚠️ {backend.name} compare failed: {e} — falling back to DDG")

    ddg = DDGBackend()
    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = ddg.raw(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison — {aspect.upper()}", "─" * 40]
    for item in items:
        lines.append(f"\n▸ {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  • {r['snippet']}")
            if r.get("url"):
                lines.append(f"    {r['url']}")
    return "\n".join(lines)


# ── Briefing helper ────────────────────────────────────────────────────────────

def _gemini_headlines(n: int = 5) -> tuple[list[str], str]:
    """Fetches current headlines via Gemini grounded search. Kept as a thin
    wrapper for existing callers (startup briefing)."""
    return GeminiGroundedBackend().headlines(n)


# ── Public entry point ─────────────────────────────────────────────────────────

def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode",  "search").lower().strip()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"
    city   = params.get("city", "").strip()

    if not query and not items:
        return "Please provide a search query."

    if items and mode not in ("compare",):
        mode = "compare"

    if player:
        player.write_log(f"[Search:{mode}] {query or ', '.join(items)}")

    print(f"[WebSearch] 🔍 mode={mode!r}  query={query!r}")

    try:
        if mode == "compare" and items:
            return _compare(items, aspect)
        if mode == "news":
            return _news(query)
        if mode == "research":
            return _research(query)
        if mode == "price":
            return _price(query)
        if mode == "events":
            return _events(query, city)
        return _search(query)

    except Exception as e:
        print(f"[WebSearch] ❌ All backends failed: {e}")
        return f"Search failed: {e}"


# ── Registry-native tool spec ───────────────────────────────────────────────

from core.tool_registry import ToolSpec


def _handle(args: dict, ctx) -> str:
    r = web_search(parameters=args, player=ctx.ui)
    result = r or "Done."
    # Mirror results to the on-screen content panel
    mode = args.get("mode", "search")
    if r and not r.startswith("No results") and not r.startswith("Search failed"):
        query = args.get("query") or ", ".join(args.get("items", []))
        label = f"{mode.upper()} — {query[:38]}" if query else mode.upper()
        ctx.ui.show_content(label, r)
    return result


TOOLS = [
    ToolSpec(
        name="web_search",
        declaration={
            "name": "web_search",
            "description": (
                "Searches the web. Use for ANY question about current facts, events, prices, "
                "or topics — always prefer this over guessing. "
                "Modes: 'search' (default), 'news' (latest headlines on a topic), "
                "'research' (deep comprehensive answer), 'price' (product cost lookup), "
                "'compare' (side-by-side comparison of items), 'events' (local events/things to do — "
                "city auto-fills from memory if omitted)."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query":  {"type": "STRING", "description": "Search query or topic"},
                    "mode":   {"type": "STRING", "description": "search | news | research | price | compare | events"},
                    "items":  {"type": "ARRAY",  "items": {"type": "STRING"}, "description": "Items to compare (compare mode)"},
                    "aspect": {"type": "STRING", "description": "Comparison aspect: price | specs | reviews | features"},
                    "city":   {"type": "STRING", "description": "City for events mode. Omit to use the user's saved city; only ask the user if none is known."},
                },
                "required": ["query"]
            }
        },
        routing_hint=(
            "web_search: mode='news' for current events, mode='research' for deep topics, "
            "mode='price' for product costs, mode='events' for local events / concerts / "
            "things to do / what's happening (city auto-fills from memory — only ask the "
            "user if it's unknown)."
        ),
        handler=_handle,
    )
]
