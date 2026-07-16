# Local discovery pipeline — "What can I do this weekend?"

The end goal: the user asks "what can I do this weekend?" and Jarvis answers —
instantly, by voice — from their interests and location: metal concerts, Meetup
hikes, AI entrepreneur events, a good trail for the weather. The same machinery
must work for a user in Vancouver and a user in Brazil, which forces the core
design rule of this whole document:

> **Code procedures, never sources.** No site name, platform, or city is ever
> hardcoded. Anything city-specific must be *discovered at runtime* and stored
> as data (in the vault), where it can be inspected, corrected, and replaced.

## The three hard problems, and where each is answered

1. **How does Jarvis know what sites to browse?** It doesn't, a priori. A
   *source bootstrap procedure* (L3) discovers per-city sources by asking the
   search layer meta-questions ("where do people in {city} find {category}
   events?"), probing the candidates, and recording survivors in the vault
   (L2). The user can also just tell it, conversationally or by editing the
   vault in Obsidian.
2. **What should it trust?** Trust is *earned per source* (L2 stats + score,
   updated by every fetch and every user reaction) and *checked per event*
   (cross-source corroboration in L5). Unverified things get presented as
   unverified — never silently promoted.
3. **How does it ask the right questions, given interests?** A query planner
   (L5) expands interests × city × timeframe into concrete, localized search
   queries using an LLM call — so "metal" in Vancouver becomes different
   queries (and a different language) than "sertanejo" in Campinas. No
   hardcoded English query templates.

## Decisions already made (with the user, 2026-07-15)

- **Delivery: background index.** A scheduled background refresh builds a
  local events index; asking is instant (reads the index), live search only
  fills gaps. No 60-second silences in a voice conversation.
- **Source access: search + plain HTTP fetch + LLM extraction only.**
  Official platform APIs (Meetup, Ticketmaster, Eventbrite, …) and a headless
  browser for JS-only sites are **future options** — the fetch layer (L0) and
  source registry (L2) are shaped so either can be added as a new fetcher/
  source-kind later, but neither is planned now.
- **Interests: implicit + feedback.** Learned from conversation (existing
  `save_memory` facts), followed topics, and reactions to suggestions. A
  guided **onboarding interview is a future option** to seed the profile —
  leave the seam (L4 doesn't care where weights come from), don't build it.
- **Scope: events + activities.** Scheduled listings (concert, meetup) AND
  non-scheduled suggestions (trail, exhibit, day trip). The activity half is
  fuzzier to rank and can't be "verified" like a listing — by design.

## Existing infrastructure this builds on (do not reinvent)

| Need | Already exists |
|---|---|
| Provider-neutral grounded search with citations | `core/search_provider.py` — `backend_chain()`, `SearchResult`, `Source` |
| One-shot LLM calls (extraction, query planning, ranking) | `core/cloud_llm.py` — `generate_text(role=...)` |
| User's city / language / topics, cached | `core/user_context.py` — `get_user_context()` |
| Single-file tool registration + routing hints | `core/tool_registry.py` — `ToolSpec` |
| Vault notes: machine frontmatter / user-owned body, atomic writes | `memory/vault_manager.py` — `_read_note`/`_write_note` contract |
| Long-running daily background task pattern | `main.py::_run_topic_digest` (compose off-session, speak via `send_text`) |
| Structured-result seam for tools | upgrade-plan Part 1D (`ToolResult`) — L6 is its first real consumer |

---

## The six layers

### L0 — Page fetch + extract primitive (`core/page_fetcher.py`)

The missing primitive in the codebase: nothing today can *read a web page*
(search grounding returns synthesis; DDG returns snippets; `browser_control`
opens a browser for the human).

- `fetch_page(url) -> FetchedPage(url, final_url, status, text, fetched_at)` —
  plain HTTP GET (requests, sane UA, timeout, size cap), HTML → readable text
  (strip nav/script boilerplate; `readability-lxml` or equivalent small dep).
- `extract_structured(page, schema_description, *, role="fast") -> dict` —
  one `cloud_llm.generate_text` call: page text in, JSON out, validated
  against the caller's expected shape. Generic — events are just one caller.
- Failure is data, not an exception: a `FetchedPage` with `status`/error set,
  so L2 can count it against the source's reliability.
- **Future option (comment in code, not built):** a `HeadlessFetcher` with the
  same signature for JS-rendered sites; platform-API adapters likewise slot in
  as alternate fetchers keyed off the source's `kind` (L2).

### L1 — Event/Activity schema + local index

```python
@dataclass
class Event:                      # scheduled, listable, verifiable
    id: str                       # hash of (normalized title, date, city)
    title: str
    category: str                 # normalized interest category slug
    start: datetime; end: datetime | None
    venue: str; city: str
    url: str                      # ALWAYS present — trust rule: no URL, no event
    source: str                   # Sources/<slug> it came from
    corroborated_by: list[str]    # other source slugs reporting the same event
    confidence: float             # from source trust + corroboration
    price: str | None
    summary: str                  # 1-2 spoken-style sentences

@dataclass
class Activity:                   # non-scheduled suggestion
    id: str; title: str; category: str
    city: str; url: str; source: str
    weather_sensitive: bool       # rank against the forecast at answer time
    summary: str
```

- **Index storage**: JSON file in `CONFIG_DIR` (e.g.
  `config/discovery_index.json`) — ephemeral machine data with a
  `generated_at` stamp, *not* vault notes (regenerated weekly; the vault is
  for durable human-meaningful state).
- **Vault rendering**: each refresh also writes
  `JarvisVault/Digests/This Weekend.md` — a human-readable digest note
  (machine-overwritten each refresh, standard frontmatter) so the index is
  browsable in Obsidian, consistent with the vault-first philosophy.

### L2 — Source registry (vault `Sources/<slug>.md`)

One note per known event source. Same contract as `Topics/`: frontmatter is
machine-owned, body is user-owned.

```yaml
---
type: source
url: https://www.meetup.com/find/?location=ca--vancouver
kind: listing-page          # listing-page | feed | (future: api | headless)
city: Vancouver
language: en
categories: [hiking, tech]
discovered: bootstrap        # bootstrap | user-told | user-edited
trust: 0.7                   # 0..1, earned (see trust model)
stats: {fetches: 12, failures: 1, events_yielded: 48, corroborated: 30}
last_verified: 2026-07-12
---
(user notes here survive rewrites — e.g. "the good stuff is in the sidebar")
```

- The user hand-adding a source in Obsidian (or saying "my city posts
  everything on VancouverIsAwesome") is a first-class path — `discovered:
  user-told` sources start at higher trust than bootstrap finds.
- `search_memory` should match these notes too (folder joins the existing
  `CATEGORY_FOLDERS` map) so "what sources do you use?" is answerable.

### L3 — Source bootstrap procedure

Given `(city, interest categories, language)` — all from `get_user_context()`
+ L4:

1. **Meta-search** per category via `backend_chain()`: "where do people in
   {city} find out about {category} events?", asked *in the local language*
   (LLM-translated; the user's `language` and the city's country inform this).
   Grounding citations (already surfaced by `SearchResult.sources`) are the
   candidate URLs.
2. **Probe** each candidate with L0: fetch, then one extraction call asking
   "does this page contain multiple future-dated event listings for {city}?"
   → yields (is_listing, categories seen, sample events).
3. **Score & record**: survivors become `Sources/` notes at modest initial
   trust; duds are recorded with `trust: 0` so they aren't re-probed weekly.
4. **Re-run triggers**: city change (compare against index's city), a category
   with zero productive sources, staleness (e.g. quarterly), or explicit
   "find better sources for X".

This is the portability answer: Vancouver and Campinas run the *same four
steps* and end up with entirely different `Sources/` folders.

### L4 — Interest model (vault `Core/Interests.md`)

Weighted interest entries in machine-owned frontmatter `fields`, same shape as
`Core/Preferences.md`:

```yaml
fields:
  metal-concerts: {weight: 0.9,  updated: 2026-07-12, signals: 4}
  hiking:         {weight: 0.8,  updated: 2026-07-01, signals: 3}
  country-music:  {weight: -0.6, updated: 2026-06-20, signals: 2}  # negative = suppress
```

Signal sources, in increasing authority: inferred from saved facts/followed
topics < explicit statement ("I love live metal") < reaction to a suggestion
("went, loved it" / "not my thing" — via L6 feedback). Weights nudge, never
jump; negatives suppress but a strong explicit statement can flip them.
`build_core_prompt_block()` is *not* extended with this — interests reach the
model through the discovery pipeline and `search_memory`, not standing prompt
text. **Future option (comment):** onboarding interview seeds this file; L4
consumes weights identically regardless of where they came from.

### L5 — Discovery orchestrator (background task)

The weekly heartbeat, following `_run_topic_digest`'s pattern (blocking work
in an executor, date-stamped so it never double-runs, only stamped on
success):

1. **Schedule**: default Thursday + a light Saturday-morning top-up (weekend
   focus), configurable in Settings.
2. **Query plan**: one `generate_text(role="fast")` call turns
   (interests × city × timeframe) into concrete localized queries — e.g.
   `metal-concerts, Vancouver, Jul 18–20` → "metal shows vancouver this
   weekend", "punk metal gigs vancouver july". Planner output is logged into
   the run so bad plans are debuggable.
3. **Fan-out**: per query, `backend_chain()` search; per trusted source
   (trust ≥ threshold), L0 fetch + event extraction. Budgeted: cap fetches
   per run, skip sources that failed recently.
4. **Normalize → dedupe → corroborate**: extraction to L1 `Event`s; dedupe on
   `id` (title+date+city); events found via ≥2 independent sources get
   `corroborated_by` and a confidence boost.
5. **Rank**: interest weight × confidence × logistics (date proximity;
   weather via the existing weather path for `weather_sensitive` activities).
6. **Write**: index JSON + `Digests/This Weekend.md`; update every touched
   source's `stats` and recompute `trust` — the loop that makes trust earned.

### L6 — Tool surface (registry-native, `actions/discovery.py`)

- **`whats_happening`** — params: `timeframe` ("today"/"weekend"/"week"),
  `category` (optional). Reads the index and answers instantly. If the index
  is stale (> ~5 days) or empty for the asked category: answer from what
  exists, say so, and trigger a targeted live top-up in the background
  (proactive follow-up when it lands). Returns structured data alongside the
  spoken text — the first real consumer of the Part 1D `ToolResult` seam, so
  "tell me more about the second one" and "open the tickets page" (existing
  `browser_control`) work off the same turn.
- **`record_event_feedback`** — `event_id`/title + reaction (went/loved/
  disliked/not-interested). Routes into L4 weight nudges and L2 source trust.
  Routing hint teaches the model to call it when the user reacts to a
  suggestion naturally in conversation.

## Trust model (cross-cutting)

- **Provenance rule**: every presented item traces to a fetched URL. No
  model-memory events, ever — an event without a source URL does not exist.
- **Speech rule**: corroborated or high-trust-source events are stated
  plainly; single-source uncorroborated ones are voiced as such ("there's
  also X on Saturday, though I could only find one listing for it").
- **Score sketch** (tune later): trust moves toward the source's observed
  hit-rate — successful probe/fetch and corroborated events pull it up,
  failures and events contradicted elsewhere pull it down, user feedback
  pulls hardest, and staleness decays it slowly. Clamp [0,1]; `user-told`
  sources floor at ~0.5.

## Build phases (each gets its own narrowing plan before implementation)

| Phase | Scope | Exit criteria |
|---|---|---|
| **A** | L0 fetcher + L1 schema/index | Fetch+extract a real listing page into valid `Event`s; index round-trips |
| **B** | L2 sources + L3 bootstrap | Fresh vault + a city name → non-empty, probed `Sources/` folder, no hardcoded sites |
| **C** | L4 interests + L5 orchestrator | Scheduled run produces ranked index + Digest note; trust stats update |
| **D** | L6 tools + feedback + trust hardening | "What can I do this weekend?" answers instantly by voice; feedback shifts weights & trust |

Portability check before calling any phase done: nothing city-, language-, or
site-specific in code — grep for site names in `core/`/`actions/` should come
up empty (they may only appear as *data* in the vault).
