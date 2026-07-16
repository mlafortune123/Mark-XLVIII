# JARVIS upgrade plan — news / local events / reservations foundations

Five parts. Part 1 is the architectural foundation; Parts 2–5 are the concrete
features from the architecture review (conversational topic follow, digest
history, grounding citations, location + events mode). Recommended build
order is at the bottom — it is not 1→5 linear.

---

## Part 1 — Abstracted architecture (foundation)

Goal: adding a new tool, a new AI provider, or a new search backend should
each be a one-file change, not a four-file scavenger hunt. Three seams need
abstracting; the live-voice layer (`core/live_voice.py`'s `LiveVoiceSession`
ABC) is already properly abstracted and is explicitly out of scope.

### 1A. Tool registry (new: `core/tool_registry.py`)

**Problem**: adding one tool currently touches four places — an import in
`main.py`, an entry in `TOOL_DECLARATIONS` (~line 83), an `elif` branch in
`_dispatch_tool()` (~line 683), and a routing hint in `core/prompt.txt`.

**Design**:

```python
# core/tool_registry.py
@dataclass
class ToolContext:          # replaces the ad-hoc player=/speak=/response= kwargs
    ui: object              # JarvisUI facade
    speak: Callable         # JarvisLive.speak
    # room to grow: vault handle, session info

@dataclass
class ToolSpec:
    name: str
    declaration: dict            # Gemini schema — stays the single source of truth
    handler: Callable[[dict, ToolContext], str]   # sync; dispatcher wraps in executor
    routing_hint: str | None = None   # one line for the system prompt's TOOL ROUTING
    blocking: bool = True             # False → handler already async / non-executor

REGISTRY: dict[str, ToolSpec] = {}
def register(spec: ToolSpec): ...
def all_declarations() -> list[dict]: ...
def routing_block() -> str: ...       # assembles TOOL ROUTING lines from hints
```

- Each `actions/*.py` module declares its own `TOOLS: list[ToolSpec]` next to
  the implementation. `main.py` imports the modules and registers them.
- `main.py::TOOL_DECLARATIONS` becomes `all_declarations()` + the few
  stateful inline tools; `_dispatch_tool()` becomes: registry lookup →
  executor call with `ToolContext` → fall through to the legacy `elif` chain
  for not-yet-migrated tools.
- `core/tool_schema.py`'s Gemini→OpenAI conversion is unchanged — it already
  consumes the declarations list, wherever it comes from.
- Routing hints get appended to the system prompt by
  `_build_system_prompt()` (dynamic `TOOL ROUTING` section) so
  `core/prompt.txt` no longer needs manual edits per tool. Keep prompt.txt's
  existing routing lines until their tools are migrated, then delete them.

**Migration strategy — incremental, not big-bang**: the registry and the
legacy `elif` chain coexist. Migrate simple stateless tools first
(`web_search`, `weather_report`, `reminder`, `youtube_video`,
`send_message`, `open_app`). **Do not migrate** `screen_process` /
`close_camera` (they mutate `JarvisLive` vision state: `_vision_busy`,
`_pending_vision`, cooldowns) or `save_memory`/`search_memory` (trivial,
and they short-circuit before the try block) until the pattern is proven.
Part 2's new topic tool should be the first registry-native tool — it
proves the pattern on something new rather than by breaking something old.

### 1B. Search backend abstraction (new: `core/search_provider.py`)

**Problem**: `actions/web_search.py` hardcodes Gemini (`genai.Client` inline,
`gemini-2.5-flash` literal) and treats every non-Gemini provider as
"scrape DDG". Results are prose-only — no structure for anything downstream
(citations, events, reservations) to consume.

**Design**:

```python
@dataclass
class Source:
    title: str
    url: str

@dataclass
class SearchResult:
    text: str                     # synthesized prose (what gets spoken)
    sources: list[Source]         # grounding citations (Part 4 fills this)
    backend: str                  # "gemini-grounded" | "ddg" | ...
    data: dict | None = None      # structured payload (Part 5 events use this)

class SearchBackend(Protocol):
    name: str
    def search(self, query: str, *, extra_instruction: str = "") -> SearchResult: ...

def backend_chain() -> list[SearchBackend]:
    # ordered by active provider: gemini → [GeminiGrounded, DDG]
    #                             openai → [OpenAIWebSearch?, DDG]
    #                             anthropic → [AnthropicWebSearch?, DDG]
```

- `GeminiGroundedBackend` absorbs `_gemini_search()` (client via
  `core/cloud_llm.py::_get_client` instead of constructing its own; model
  name from a `_MODELS`-style constant, not a string literal mid-function).
  It always applies `_recency_instruction()` + the caller's
  `extra_instruction` (this is how Part 5 injects location).
- `DDGBackend` absorbs `_ddg_search`/`_ddg_news`.
- **Fixes the provider asymmetry for real**: OpenAI's Responses API has a
  native `web_search` tool and Anthropic has a server-side web search tool —
  each becomes a backend later without touching mode logic. (Verify both
  APIs' current names/shapes when implementing; don't trust this doc.)
- `actions/web_search.py` keeps its public `web_search(parameters, ...)`
  entry point and mode functions, but modes become thin: build the query +
  extra instruction, walk `backend_chain()`, format `SearchResult` → str at
  the edge. Replace `_news()`'s quality-nondeterministic race (first result
  >60 chars wins — DDG usually beats the better backend on latency) with:
  primary backend with a ~6–8s budget, fallback only on failure/timeout.
- The `_recency_instruction()` convention (CLAUDE.md gotcha 12) moves into
  the backend so it is impossible to forget on a new grounded call.

### 1C. User context service (new: `core/user_context.py`)

**Problem**: personalization data is scattered — `weather_city` in
Settings.md, `city`/`language`/`name` in Identity.md, followed topics in
Settings — and read via ad-hoc `get_identity_field()` / `get_settings()`
calls in `main.py`, `proactive.py`, and (after Part 5) `web_search.py`.

**Design**: one read-mostly accessor over the vault:

```python
@dataclass
class UserContext:
    name: str | None
    city: str | None          # Identity city, falling back to weather_city
    language: str | None
    followed_topics: list[str]
    now: datetime             # local wall clock — pairs with recency anchoring

def get_user_context() -> UserContext   # short TTL cache (~60s), vault-backed
```

Consumers: `web_search` events mode (Part 5), startup briefing, topic
digest, `proactive.py`. Migrate call sites opportunistically — no flag-day.

### 1D. Structured tool results (convention, not framework)

Actions may return a `ToolResult(speech_text, data, ui_label)` instead of a
bare `str`; the dispatcher sends `speech_text` + serialized `data` back as
the function response so the live model sees structure (URLs, event lists)
it can act on ("open the second one", "book that"). Bare-`str` returns stay
valid forever. This is the seam the future reservation tier
(`propose_reservation` → confirm → `confirm_reservation`) plugs into — the
reservation tier itself is deliberately not in this plan.

**Part 1 exit criteria**: one new tool registered without editing
`_dispatch_tool` or `prompt.txt`; `web_search` runs through `backend_chain()`
with identical user-visible behavior; `SearchResult` exists end-to-end.

---

## Part 2 — Follow/unfollow topics conversationally

**Problem**: `set_followed_topics()` is reachable only from the Preferences
UI (`ui.py:2943`). "Keep me posted on the F1 season" has no tool path.

**Changes**:

1. `memory/vault_manager.py` — add:
   - `follow_topic(name: str) -> str` — case-insensitive dedup against
     `list_followed_topics()` (compare slugs, not raw strings), append,
     `set_followed_topics(updated)`. Returns a speakable confirmation.
   - `unfollow_topic(name: str) -> str` — match by slug **or** display name;
     removal already keeps the note and just strips the `followed` tag.
2. New tool `manage_topics` (one tool, not three — keeps `TOOL_DECLARATIONS`
   small): params `action: follow|unfollow|list` (required),
   `topic: STRING` (required unless list). Register via the Part 1A registry
   — this is the pattern-proving tool. Declaration lives next to a thin
   handler (in `vault_manager` or a small `actions/topics.py`).
3. Routing hint (via `routing_hint`, or prompt.txt if built before Part 1A):
   "keep me posted on / follow / stop following / what do I follow →
   manage_topics. Do NOT use save_memory for topic following."
   The last clause matters — today the model's only outlet for "follow X" is
   misfiling it as a `notes` fact.

**Interactions to check**: the Preferences panel pre-fills topics from
settings on open and force-mutes the mic while open (CLAUDE.md gotcha 8), so
UI-vs-voice write conflicts are effectively impossible; last-write-wins via
`save_settings` is acceptable. Migration: none — same storage.

**Verify**: say "follow SpaceX for me" → `Settings.md` frontmatter gains it,
`Topics/spacex.md` exists with `followed` tag, Preferences panel shows it;
"stop following SpaceX" strips the tag but keeps the note.

---## Part 3 — Digest history (stop repeating the same news)

**Problem**: `_run_topic_digest()` (`main.py:1060`) tells the *live* model to
call `web_search` per topic and speak. Nothing records what was reported, so
slow-moving topics repeat daily. Also serial + expensive inside the live
session.

**Design decision — move digest composition out of the live session**:

1. Background task (plain `asyncio` task, as now) composes the digest itself:
   - For each followed topic: `backend_chain()` search (Part 1B) with a news
     framing + the topic's stored history: *"Previously reported to the user:
     {last N summaries}. Report only developments NEWER than these; if
     nothing new, say 'no significant updates' in one clause."*
   - One `core/cloud_llm.py::generate_text(role="fast")` call to compress
     per-topic results into 1–2 spoken sentences each.
2. Store what was reported — machine-owned frontmatter on
   `Topics/<slug>.md` (body stays user-owned, per vault contract):
   ```yaml
   digest_history:
     - {date: 2026-07-15, summary: "Starship flight 12 cleared FAA review…"}
   ```
   Cap at ~14 entries (rolling). New vault helpers:
   `append_digest_history(topic, summary)`, `get_digest_history(topic, n=5)`.
3. Deliver via the existing pattern: `send_text("[TOPIC DIGEST] Read this
   briefing naturally, do not call any tools: …")` — same tag convention
   prompt.txt already documents, but the model now just performs the text.
4. Make history searchable: `search_memory()`'s haystack currently joins
   stem/key/value/tags/body — add `digest_history` summaries so "what did you
   tell me about SpaceX yesterday" hits.

**Why not a `record_digest` tool the live model must call**: relies on the
model remembering bookkeeping mid-conversation; fails silently. Rejected.

**Fallback behavior**: if all backends fail for a topic, skip it silently in
the digest and do not write history (so tomorrow retries fresh).

**Verify**: run digest twice same day → second no-ops (existing
`topic_digest_last` guard); force two runs across fake dates → second run's
prompt contains history and output differs; check `Topics/<slug>.md` in
Obsidian renders cleanly.

---

## Part 4 — Keep grounding citations (URLs)

**Problem**: `_gemini_search()` collects only `part.text` and discards
`grounding_metadata` — the citation URLs Gemini already returns. Events and
reservations are dead without URLs ("book that one" needs *which venue*).

**Changes** (inside `GeminiGroundedBackend` after Part 1B; same extraction
works in `_gemini_search()` if built before):

1. Extract from `response.candidates[0].grounding_metadata`:
   `grounding_chunks[].web.{uri, title}` → `SearchResult.sources`
   (dedup by URL, cap ~5). Field names must be re-verified against the
   installed `google-genai` version — grounding metadata shapes have shifted
   across SDK releases. URIs are Google redirect links
   (`vertexaisearch.cloud.google.com/...`) — functional, ugly; lead with
   `title`.
2. Formatting at the edge (`web_search.py`): append a compact block —
   ```
   Sources:
   1. Starship flight 12 — SpaceNews (https://…)
   ```
   The live model sees URLs in the tool result → "open the third one"
   already works via the existing `browser_control` tool, no new wiring.
3. `_gemini_headlines()` gets the same treatment (it shares the backend).
4. DDG paths already carry URLs per-result — normalize them into
   `SearchResult.sources` too, so downstream code never cares which backend
   ran.
5. Prompt-space cost: sources add ~300–500 chars per search result fed back
   into the live session. Acceptable; cap at 5 sources.

**Verify**: `web_search(mode='news', query='SpaceX')` on Gemini provider →
result ends with a Sources block whose URLs resolve; same call with Gemini
key removed → DDG path still produces sources.

---

## Part 5 — Unified location + `events` mode

**Problem**: location lives in two disconnected fields — `weather_city`
(Settings, used only by the briefing) and `city` (Identity, prompt-injected
prose only). `web_search()` never reads the vault; "find something to do
this weekend" is location-anchored only if the live model remembers to put
the city in the query.

**Changes**:

1. **Location resolution** (Part 1C): `UserContext.city` = Identity `city`,
   else `weather_city`. Write path stays `save_memory(category='identity',
   key='city', …)` — already works conversationally. Do **not** delete
   `weather_city` (Preferences UI writes it); just make Identity win.
   One-time nicety in `migrate_if_needed()`-style guard: if Identity has no
   city and `weather_city` is set, copy it into Identity.
2. **New `web_search` mode `events`** in `actions/web_search.py`:
   - Tool schema: add `city` (optional STRING) to `web_search` params; mode
     enum gains `events`.
   - `_events(query, city)`: resolve `city or get_user_context().city`; if
     neither, return a prompt for the model to ask the user — do not guess.
   - Grounded query: `"Events in/near {city}: {query}. Include specific
     dates, venue names, and ticket/booking links."` plus an
     `extra_instruction` location anchor alongside the recency instruction:
     *"The user is located in {city}; local time is {now}. 'This weekend' /
     'tonight' resolve relative to that."*
   - DDG fallback: `ddgs.text(f"{query} events {city} {month year}")`.
   - Part 4's sources make results bookable-adjacent (links surface).
3. **Routing hint**: "events / concerts / things to do / what's happening →
   web_search mode='events' (city auto-fills from memory — only ask if
   unknown)."
4. **Weather briefing** (`_send_startup_briefing`, `_briefing_weather_phase`)
   switches to the unified resolver — behavior identical for existing users,
   but a conversationally-saved city now enables weather without touching
   Preferences.

**Explicitly deferred**: structured event APIs (Ticketmaster/Eventbrite),
geolocation, timezone-aware travel handling, and the reservation tier.
The seam for all of them is `SearchResult.data` + `ToolResult` (Part 1D).

**Verify**: with city saved in Identity only → "what's happening this
weekend" produces city-anchored results with source links; with no city
anywhere → Jarvis asks instead of guessing; weather briefing still fires
for a user who only ever set `weather_city`.

---

## Recommended build order

Dependencies, not part numbers:

1. **Part 1B** (search backend + `SearchResult`) — underpins 3, 4, 5.
2. **Part 4** (citations) — smallest diff once 1B exists; immediately useful.
3. **Part 1C** (user context) — small; unblocks 5 and cleans up briefing/digest reads.
4. **Part 5** (events mode) — needs 1B + 1C + 4.
5. **Part 1A** (tool registry) — independent of search work; do when touching
   `TOOL_DECLARATIONS` anyway, i.e. right before…
6. **Part 2** (follow/unfollow) — first registry-native tool.
7. **Part 3** (digest history) — last; benefits from 1B (backend search),
   1C (language/name reads), and 2 (topics actually accumulate).

Standing constraints (from CLAUDE.md, apply to every part): two independent
Gemini Live sessions exist — delivery/prompt changes must check
`actions/screen_processor.py` too (gotcha 5); prompt overrides are
positional, append-last (gotcha 4); every new grounded call carries the
recency instruction (gotcha 12); `macOS` has no GNU `timeout` for verify
scripts (gotcha 6).
