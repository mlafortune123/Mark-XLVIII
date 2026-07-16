"""
core/search_provider.py — provider-neutral web search backends.

Replaces actions/web_search.py's hardcoded "Gemini inline client, DDG as the
only fallback" shape with a small chain of backends, each returning a
structured SearchResult (prose + citation sources + optional structured
data) instead of a bare string. actions/web_search.py stays the public tool
entry point — it just walks backend_chain() and formats the result at the
edge.

See CLAUDE.md gotcha 12 — every Gemini grounded call must carry the
recency instruction, which is why it's baked into GeminiGroundedBackend
rather than left to each caller to remember.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from core.cloud_llm import get_provider, get_client, model_for


def _recency_instruction() -> str:
    """System instruction anchoring grounded search calls to the real
    wall-clock date. Without this, google_search grounding still fetches
    live results, but the model's own synthesis of them isn't told today's
    actual date or that it should trust live grounding over its (older)
    training data — leading to stale-feeling answers even when the
    underlying search results were current. Apply this to every one-shot
    Gemini call that uses google_search grounding — see claude.md's
    "Search recency" gotcha before adding a new one without it."""
    now = datetime.now()
    return (
        f"Today's real date is {now.strftime('%A, %B %d, %Y')}. This is "
        "ground truth — your training data has an earlier cutoff and may be "
        "stale or wrong about anything time-sensitive. Trust the search "
        "results over your own memorized knowledge. Prioritize the most "
        "recent, currently relevant information; if results conflict or "
        "include older material, prefer the newer one and say so if it "
        "matters. Never present outdated information as current."
    )


@dataclass
class Source:
    title: str
    url: str


@dataclass
class SearchResult:
    text: str                       # synthesized prose (what gets spoken)
    sources: list[Source] = field(default_factory=list)   # grounding citations
    backend: str = ""                # "gemini-grounded" | "ddg" | ...
    data: dict | None = None         # structured payload (events etc.)


class SearchBackend(Protocol):
    name: str

    def search(self, query: str, *, extra_instruction: str = "") -> SearchResult: ...


MAX_SOURCES = 5


def _dedup_sources(sources: list[Source]) -> list[Source]:
    seen: set[str] = set()
    out: list[Source] = []
    for s in sources:
        if not s.url or s.url in seen:
            continue
        seen.add(s.url)
        out.append(s)
        if len(out) >= MAX_SOURCES:
            break
    return out


class GeminiGroundedBackend:
    """Gemini's built-in google_search grounding tool. Gemini-only — raises
    if the active provider isn't Gemini so callers fall through to the next
    backend in the chain."""

    name = "gemini-grounded"

    def _generate(self, contents: str, system_instruction: str):
        if get_provider() != "gemini":
            raise RuntimeError("Native web search requires the Gemini provider.")
        client = get_client("gemini")
        model  = model_for("gemini", "default")
        return client.models.generate_content(
            model=model,
            contents=contents,
            config={
                "tools": [{"google_search": {}}],
                "system_instruction": system_instruction,
            },
        )

    def _extract_sources(self, response) -> list[Source]:
        # google-genai's grounding_metadata shape has shifted across SDK
        # releases (CLAUDE.md gotcha) — extract defensively, never let a
        # missing/renamed field break the actual search result.
        sources: list[Source] = []
        try:
            candidate = response.candidates[0]
            gm = getattr(candidate, "grounding_metadata", None)
            chunks = getattr(gm, "grounding_chunks", None) or []
            for chunk in chunks:
                web = getattr(chunk, "web", None)
                if not web:
                    continue
                uri   = getattr(web, "uri", "") or ""
                title = getattr(web, "title", "") or uri
                if uri:
                    sources.append(Source(title=title, url=uri))
        except Exception as e:
            print(f"[SearchProvider] ⚠️ Could not extract grounding sources: {e}")
        return _dedup_sources(sources)

    def search(self, query: str, *, extra_instruction: str = "") -> SearchResult:
        instruction = _recency_instruction()
        if extra_instruction:
            instruction = f"{instruction} {extra_instruction}"

        response = self._generate(query, instruction)

        text = ""
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                text += part.text
        text = text.strip()
        if not text:
            raise ValueError("Gemini returned an empty response.")

        return SearchResult(text=text, sources=self._extract_sources(response), backend=self.name)

    def headlines(self, n: int = 5) -> tuple[list[str], str]:
        """Briefing helper — numbered top-headline titles only, minimal prompt
        + strict token budget for speed."""
        import re

        response = self._generate(
            f"Current world news: {n} headlines. Numbered list, titles only.",
            _recency_instruction(),
        )

        raw = ""
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                raw += part.text

        headlines = []
        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if not re.match(r'^[\d]+[.\)\-]', line):
                continue
            clean = re.sub(r'^[\d]+[.\)\-]\s*', '', line)
            clean = re.sub(r'^\*+\s*',          '', clean).strip()
            if clean and len(clean) > 10:
                headlines.append(clean)

        return headlines[:n], raw.strip()


class DDGBackend:
    """DuckDuckGo fallback — no API key required, works regardless of the
    active AI provider."""

    name = "ddg"

    def _client(self):
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        return DDGS

    def raw(self, query: str, *, news: bool = False, max_results: int = 6) -> list[dict]:
        """Unformatted result dicts (title/snippet/url[/source]) — used
        directly by callers that need to reason about individual results
        (e.g. comparing several items), not just the formatted blob."""
        DDGS = self._client()
        results: list[dict] = []
        try:
            with DDGS() as ddgs:
                if news:
                    for r in ddgs.news(query, max_results=max_results):
                        results.append({"title": r.get("title", ""), "snippet": r.get("body", ""),
                                         "url": r.get("url", ""), "source": r.get("source", "")})
                else:
                    for r in ddgs.text(query, max_results=max_results):
                        results.append({"title": r.get("title", ""), "snippet": r.get("body", ""),
                                         "url": r.get("href", "")})
        except Exception as e:
            if news:
                print(f"[SearchProvider] ⚠️ DDG news() failed ({e}) — falling back to text search")
                return self.raw(query, news=False, max_results=max_results)
            raise
        return results

    def search(self, query: str, *, extra_instruction: str = "", news: bool = False,
               max_results: int = 6) -> SearchResult:
        results = self.raw(query, news=news, max_results=max_results)
        if not results:
            return SearchResult(text="", sources=[], backend=self.name)

        lines = []
        sources = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            if not title:
                continue
            src = f"  [{r['source']}]" if r.get("source") else ""
            lines.append(f"{i}. {title}{src}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet'][:140] if news else r['snippet']}")
            if r.get("url"):
                lines.append(f"   {r['url']}")
                sources.append(Source(title=title, url=r["url"]))
            lines.append("")

        return SearchResult(text="\n".join(lines).strip(), sources=_dedup_sources(sources),
                             backend=self.name)


def backend_chain() -> list[SearchBackend]:
    """Ordered fallback chain for the active provider. Every provider ends
    in DDGBackend so a search never hard-fails just because the primary
    backend errored."""
    provider = get_provider()
    if provider == "gemini":
        return [GeminiGroundedBackend(), DDGBackend()]
    # OpenAI's Responses API and Anthropic's server-side web search tool
    # each deserve their own backend eventually (verify current API shapes
    # before implementing) — for now both fall back to DDG only.
    return [DDGBackend()]
