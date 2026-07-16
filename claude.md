# CLAUDE.md — JARVIS (Mark XLVIII) architecture map

Personal, cross-platform (Windows/macOS/Linux) real-time voice assistant.
PyQt6 GUI + Gemini Live API (primary) / OpenAI Realtime API (alt) for
streaming voice conversation, plus a large set of "tool" actions the LLM can
call (system control, file ops, browser, code gen, etc.) and a FastAPI
dashboard for remote/phone control.

This file exists so an agent can find the right file on the first try
instead of grepping the whole tree. Update it when you add a subsystem,
rename a major file, or discover a non-obvious constraint — not for routine
line-level changes.

## Entry point & orchestration

- **`main.py`** — the app's brain. `JarvisLive` (class, ~line 527) owns the
  live voice session, tool dispatch, memory/preferences reads, and system
  prompt assembly. Key pieces:
  - `TOOL_DECLARATIONS` (~line 83) — Gemini-schema function declarations for
    every tool the LLM can call. This is the **single source of truth**;
    `core/tool_schema.py` converts it to OpenAI's shape on the fly, so add
    new tools only here. Includes `save_memory`/`search_memory` — see
    "Memory" section below.
  - `_dispatch_tool()` (~line 665) — routes a tool-call name to the actual
    Python function in `actions/`.
  - `_build_system_prompt()` (~line 616) — assembles the live system prompt:
    time context → `vault_manager.build_core_prompt_block()` (Core facts) →
    `core/prompt.txt` → `[LANGUAGE OVERRIDE]` → `[DELIVERY OVERRIDE]`
    (accent/style/pace merged into one block), each override appended
    **last** in its turn for instruction precedence.
  - `_preferred_language()` (~line 589) — reads the language preference;
    returns `None` for `"auto"` (see gotcha below).
  - `common_kwargs` (~line 1185) — shared constructor args passed via
    `**common_kwargs` to both `GeminiLiveSession` and `OpenAIRealtimeSession`
    (`core/live_voice.py`). This is where `voice_name` / `language_code`
    preferences get threaded into the live session.
  - `get_base_dir()` (~line 58) — resolves the app's root whether running
    from source or a PyInstaller onedir bundle (`sys._MEIPASS`/executable
    dir). Anything reading a bundled resource path should reuse this instead
    of `Path(__file__).parent`.
  - `PROMPT_PATH = BASE_DIR / "core" / "prompt.txt"` — the base system
    prompt text (persona, tone, per-turn language-detection rules, address
    conventions). Edited directly as plain text, not Python.

- **`ui.py`** — the entire PyQt6 GUI (~2900 lines), single file. Structural
  map:
  - `JarvisUI` (~line 2850) — thin facade `main.py` talks to (`muted`,
    `current_file`, `on_text_command`, etc.); wraps `MainWindow`.
  - `MainWindow` (~line 1649) — the actual `QMainWindow`: HUD canvas, log
    panel, header buttons (incl. the ⚙ **Preferences** button), overlay
    lifecycle management. Thread-safe UI updates go through `pyqtSignal`s
    (`_log_sig`, `_state_sig`, `_content_sig`, `_reconfig_sig`,
    `_cam_frame_sig`, etc.) since voice/tool work runs off the Qt thread.
  - `SetupOverlay` (~line 940) — first-run API-key/provider setup screen.
  - `OnboardingOverlay` (~line 1168) — first-run **and** reopenable
    Preferences panel (news/weather/topics/language/voice). Takes
    `initial: dict | None` to pre-fill on reopen and `closable: bool` to
    switch its bottom button between "Skip for now" (first run) and
    "Cancel" (reopened as Preferences). Emits `done(dict)` or `closed()`.
    The voice/accent/style/pace `QComboBox`es' `currentIndexChanged` all
    feed one shared debounce timer into `_play_voice_preview()`, which
    calls `core/voice_preview.py` on a background thread to speak a short
    sample of the combination. Accent/Style/Pace are Gemini-only (prompt-
    instruction-based, no effect on OpenAI voices) and are hidden entirely
    — `setVisible(False)`, not disabled — when the active provider is
    OpenAI, same reasoning as the preview no-op above. `_show_preferences()`
    force-mutes the mic for as long as the panel is open (restored to
    whatever it was before, on close via `_close_preferences()`) — see
    gotcha 8 below for why.
  - `_close_overlay()` helper on `MainWindow` — **always** call this before
    swapping `self._overlay` to a new overlay. See gotcha below.
  - `HudCanvas`, `MetricBar`, `_SysMetrics` — the animated waveform/HUD and
    live CPU/RAM/GPU telemetry widgets.
  - `FileDropZone` / `_DropCanvas` — drag-and-drop file target used by
    `actions/file_processor.py`.

## Voice backends

- **`core/live_voice.py`** — provider-neutral live session abstraction.
  - `LiveVoiceSession` (ABC) — common constructor: `system_prompt`,
    `tool_declarations`, `tool_dispatch`, transcript callbacks,
    `is_muted`, `language_code`, `voice_name`. Concrete subclasses only
    consume the params their backend supports.
  - `GeminiLiveSession` — wraps `google.genai` `LiveConnectConfig`.
    `_build_config()` sets `SpeechConfig(voice_config=..., language_code=...)`.
    Voice comes from `core/voices.py::DEFAULT_VOICE` as fallback.
  - `OpenAIRealtimeSession` — wraps `gpt-realtime-2.1`. `voice_name` is
    now sent via `session.update`'s `audio.output.voice` (validated
    against `core/voices.py::OPENAI_VOICES`, falling back to
    `DEFAULT_OPENAI_VOICE` if it's holding a stale Gemini name). No
    `language_code` equivalent exists in this API — language locking for
    this backend is enforced only at the prompt level (see
    `_build_system_prompt()`), which also happens to be how accent
    locking works for *both* backends (see `core/accents.py` below).
  - google-genai is a **lazy import** everywhere in this file (`from
    google.genai import types` inside methods, not at module top) — it's
    treated as optional. If you add a method that uses `types`, import it
    locally in that method; it will NOT be visible from a sibling method
    (see gotcha below — this caused a real crash).

- **`core/tts.py`** — non-live TTS engines (Edge TTS, Kokoro, ElevenLabs).
  **Dead code as of this writing** — `create_tts_player()`/`TTSPlayer` have
  zero callers anywhere in the repo. `main.py::speak_error()` (~line 565,
  despite the name suggesting it'd use a TTS engine directly) actually just
  calls `self.speak()`, which routes through the live session's
  `send_text()` like any other spoken response — Gemini/OpenAI's Live API
  synthesizes the audio, not this file. `edge-tts`/`kokoro`/`miniaudio`
  (this file's deps) aren't even in `requirements.txt`. Don't assume this
  module runs; re-check for callers before relying on it.
  `core/voice_preview.py` (below) does its own audio decode/playback rather
  than reusing this file's `_play_audio_bytes` for that reason.
- **`core/voice_preview.py`** — one-shot (non-live) Gemini TTS call used
  only to preview a voice in Preferences (`ui.py`'s `OnboardingOverlay`,
  voice/accent/style/pace combos). Hits `client.models.generate_content(
  model="gemini-3.1-flash-tts-preview", ...)` (migrated from
  `gemini-2.5-flash-preview-tts` — see gotcha 9) with the same
  `SpeechConfig`/`PrebuiltVoiceConfig` shape `GeminiLiveSession` uses, so
  it can say `"Hey, I'm <voice>."` in the selected voice without opening a
  full Live API session (no mic capture, no tool wiring, no persistent
  connection — and the Live model *can't* be used this way regardless, see
  gotcha 9). Response audio comes back as raw 16-bit PCM in `inline_data`
  (mime type carries the sample rate, e.g. `audio/l16;rate=24000` — parsed
  rather than hardcoded, defaulting to 24000 if absent) and is played
  directly via `sounddevice.play()`, not through `core/tts.py`. A
  generation counter guards against out-of-order playback if the user
  changes any of voice/accent/style/pace again before a prior network
  round-trip finishes — only the most recent request is allowed to play.
  `ui.py` debounces all four combos' `currentIndexChanged` into one shared
  250 ms `QTimer` (connected *after* the initial `setCurrentIndex()` calls
  so restoring saved preferences on open doesn't itself fire a preview).
  - `_preview_contents()` builds the TTS prompt text: if accent/style/pace
    are all default it's just `"Hey, I'm <voice>."`; otherwise it prepends
    a natural-language director's-note (e.g. `"In a professional
    newscaster delivery style, at a normal pace, with a British
    (Received Pronunciation) English accent, say: Hey, I'm Sadaltager."`)
    — this exact phrasing was empirically validated (user-confirmed
    correct on the Sadaltager/newscaster/British combo) before being
    generalized; if audio quality regresses after touching this function,
    that's the reference case to re-test against.
  - **Lookup order** (see gotcha 9 for why): `core/voice_previews/<name>.wav`
    (bundled with the app — **only for the all-default combo**, zero API
    cost) → `<CONFIG_DIR>/voice_previews_cache/<...>.wav` (writable,
    per-machine fallback cache for anything missing from the bundle,
    including every non-default accent/style/pace combination — see
    `_cache_filename()` for the naming scheme) → live API call, which is
    then written into that cache so it's never re-fetched on the same
    machine for the same combo. `scripts/generate_voice_previews.py`
    (re)builds the bundled (all-default) set only — resumable (skips
    existing files unless `--force`), paced at one request per ~21s (see
    gotcha 9 — free tier also stacks a 3/min cap on top of the daily one;
    4s spacing wasted most of a run's budget hitting that instead of the
    actual daily limit). Both PyInstaller specs' `datas` include
    `core/voice_previews` — re-run the generation script and confirm all
    30 exist before cutting a release build.
  - `core/stt.py` — offline STT fallbacks (Whisper, Vosk), not the primary
    path (Gemini/OpenAI Live handle STT natively).

- **`actions/screen_processor.py`** — a **second, independent** Gemini Live
  session (`_session_loop()`) used only for camera/screen-share vision
  narration. It does not go through `core/live_voice.py` or
  `common_kwargs` — it builds its own `LiveConnectConfig` directly. If you
  change voice/language preference wiring, remember this file has its own
  copy of the voice_name lookup and currently does **not** read the
  language preference (only voice was wired here so far).

## Language, voice, accent, style & pace preferences

- **`core/accents.py`**, **`core/styles.py`**, **`core/pace.py`** — same
  `(code, display_name, instruction)` shape as `core/languages.py`, one
  file per dimension. **None of these map to a structured Gemini API
  field** — confirmed by inspecting `SpeechConfig`/`VoiceConfig`'s actual
  `model_fields` (only `voice_config`/`language_code`/
  `multi_speaker_voice_config` exist) and by Google's own docs: accent/
  style/pace are controlled purely through natural-language prompt text
  (e.g. `"Accent: Southern California valley girl..."`), not API
  parameters. So `instruction` here is a phrase meant to be embedded
  directly into a prompt, not passed to any config object.
  - Applied in two different ways depending on context: `core/voice_preview.py`
    embeds it directly into the one-shot TTS call's `contents` text (see
    `_preview_contents()` above); `main.py::_build_system_prompt()` and
    `actions/screen_processor.py::_session_loop()` instead append a
    `[DELIVERY OVERRIDE]` block to the system prompt (same append-last-for-
    precedence pattern as `[LANGUAGE OVERRIDE]`, gotcha 4) — style/pace/
    accent are folded into *one* block rather than three, since they're all
    the same kind of thing (prompt-instruction-only delivery controls).
  - `DEFAULT_ACCENT`/`DEFAULT_STYLE`/`DEFAULT_PACE` are all `"default"`,
    meaning "no override, don't touch the prompt" — not merely a display
    label. `main.py::_preferred_accent()`/`_preferred_style()`/
    `_preferred_pace()` return `None` in that case, same pattern as
    `_preferred_language()`'s `"auto"` handling (gotcha 3).

- **`core/languages.py`** — `SUPPORTED_LANGUAGES` list of
  `(code, display_name, gemini_locale)`. `"auto"` is a real entry with
  `display_name="Auto-detect"` — `language_name("auto")` returns a
  **truthy** string, so callers must explicitly branch on
  `code != "auto"` rather than `if language_name(code):`. `language_locale()`
  correctly returns `None` for `"auto"`.
- **`core/voices.py`** — `SUPPORTED_VOICES` list of `(name, style)` for all
  30 Gemini TTS prebuilt voices (sourced from Google's live docs, not
  memorized — re-verify against
  https://ai.google.dev/gemini-api/docs/generate-content/speech-generation
  before trusting the list is still current). `DEFAULT_VOICE = "Charon"`.
  `is_valid_voice()` for validation. Same file also holds `OPENAI_VOICES`
  (10 entries: `marin`/`cedar` + 8 legacy) + `DEFAULT_OPENAI_VOICE` +
  `is_valid_openai_voice()` — **the two catalogs are not interchangeable**
  (Gemini names are TitleCase, OpenAI's are lowercase), so anything that
  reads the `voice` preference must pick the right list for whichever
  provider is active (`core.cloud_llm.get_provider()`). `ui.py`'s VOICE
  dropdown already does this (switches catalog + default on open); the
  Gemini-only preview button (`core/voice_preview.py`) just no-ops when
  the OpenAI catalog is showing, since OpenAI's Realtime API has no
  one-shot preview endpoint to call instead.
- Both lists are imported by **both** `ui.py` (to populate the Preferences
  dropdowns) and `main.py` (to resolve the saved preference into what the
  live session needs) — never imported the other direction, since `main.py`
  already imports from `ui.py`.
- Language lock enforcement is **two-layered**: `SpeechConfig.language_code`
  at the transport level (Gemini only) *and* a `[LANGUAGE OVERRIDE]` block
  appended to the end of the system prompt in `main.py::_build_system_prompt()`
  (works for both backends, and is what beats `core/prompt.txt`'s per-turn
  auto-detect/switch instructions via recency/position, not by editing
  prompt.txt itself).

## Memory (`memory/vault_manager.py` — Obsidian vault)

`memory/preferences_manager.py` (old `config/preferences.json`) and
`memory/memory_manager.py` (old `memory/long_term.json`) **no longer
exist** — both were deleted once every call site migrated. All user
state — settings *and* long-term facts — now lives in
**`memory/vault_manager.py`**, backed by a real Obsidian vault: plain
Markdown notes with YAML frontmatter that the user can open directly in
the Obsidian app, not opaque JSON. This replaced the JSON stores rather
than augmenting them; old files are renamed to `.bak` by migration, never
deleted (see `migrate_if_needed()` below).

**Vault location**: `vault_manager.get_vault_path()` / `set_vault_path()`,
pointed to by `config/vault_path.json` (gitignored). Default
`~/Documents/JarvisVault`. `ui.py`'s `OnboardingOverlay` has a vault-path
field wired to this — **MVP is repoint-only**: changing it swaps which
folder Jarvis reads/writes, it does **not** move or copy any existing
notes there. Changing the path mid-use effectively starts a fresh vault
unless the new folder already has one.

**Structure**:
```
JarvisVault/
  Core/
    Identity.md      # small stable facts (name, city, job, language...) — always injected in full
    Preferences.md    # small stable prefs (favorite color, etc.) — always injected, capped to top 15
    Settings.md        # NOT injected as prompt text — read structurally only (get_settings())
  Topics/<slug>.md      # one per followed topic, tag "followed" — on-demand via search_memory
  People/<slug>.md      # one per relationship fact — on-demand
  Projects/<slug>.md    # one per project fact — on-demand
  Facts/<slug>.md       # wishes/notes-category facts — on-demand
```
Frontmatter fields (`type`/`category`/`key`/`value`/`tags`/`updated`, or
`fields` on the two Core files) are **machine-owned** and get overwritten
on every save; the note **body is user/Obsidian-owned** and is preserved
verbatim across rewrites — this is what keeps the vault safely
hand-editable without Jarvis clobbering notes the user has written into.

**Retrieval is hybrid, by design** (this is the actual fix for the bug
that motivated the whole rewrite — "what's the news" never used to check
followed topics):
- `build_core_prompt_block()` renders `Core/Identity.md` in full +
  `Core/Preferences.md` capped to the 15 most-recently-updated entries,
  same char-cap/truncation discipline the old `format_memory_for_prompt()`
  had (~2000 chars). Called from `main.py::_build_system_prompt()`
  (~line 617) and `actions/proactive.py::ProactiveEngine.build_prompt()`
  — both places that used to call the old `format_memory_for_prompt()`.
  This is small and *always* injected, same as before.
- Everything else — followed topics, projects, people, freeform notes —
  is growable and *not* injected by default. It's retrieved on demand via
  the **`search_memory`** LLM tool (`TOOL_DECLARATIONS`, ~line 504;
  dispatched in `_dispatch_tool()`, ~line 686), which does pure
  keyword/tag/filename substring matching over `Topics/People/Projects/
  Facts` — **no embeddings, no vector DB**, deliberately, to avoid a local
  model dependency. `core/prompt.txt`'s TOOL ROUTING section tells the
  model to call `search_memory` before a generic `web_search(mode='news')`
  when the user's request has no explicit subject, so a followed-topics
  digest can inform an ad-hoc "what's the news" the way it never did
  under the old JSON scheme.
- The identity/preferences-vs-everything-else split is a deliberate
  tiering decision, not an oversight: small stable facts stay
  always-injected (matches pre-vault behavior exactly), only
  unboundedly-growable categories moved to on-demand.

**Settings** (replaces `preferences.json`): `get_settings()` /
`save_settings(update)`, `DEFAULT_SETTINGS` dict — same
merge-on-load-is-backward-compatible-for-free pattern the old
`preferences_manager.py` had: add a key to `DEFAULT_SETTINGS`, no
migration code needed (this is how `style`/`pace` were added alongside
`accent`). Stored structurally in `Core/Settings.md` frontmatter and
**never** rendered into the prompt as text — `_preferred_language()` /
`_preferred_accent()` / `_preferred_style()` / `_preferred_pace()` in
`main.py` read individual keys off `get_settings()` directly.
`followed_topics` lives in `Settings.md` as the ordered source of truth
(`list_followed_topics()` / `set_followed_topics(names)`) and is mirrored
into `Topics/<slug>.md` notes tagged `followed` so topics are *also*
human-browsable in Obsidian and reachable by `search_memory` — removing a
topic strips the tag rather than deleting the note, in case the user
added their own content to it.

**Facts** (replaces `long_term.json` + the old `remember`/`forget`):
`save_fact(category, key, value)` / `forget_fact(key, category)` — the
`save_memory` tool's `category`/`key`/`value` schema in
`TOOL_DECLARATIONS` (~line 474) is unchanged from before the rewrite, only
its backing store changed. Category routes to a folder:
`identity`/`preferences` → merged into the relevant `Core/*.md` file's
`fields` dict; `projects`→`Projects/`, `relationships`→`People/`,
`wishes`/`notes`→`Facts/` (one note per fact). `get_identity_field(key)`
is a convenience single-field reader for callers that need just one value
rather than the whole rendered Core block — used by
`_send_startup_briefing()`/`_run_topic_digest()` for name/language
fallback when no explicit language override is locked.

**Migration**: `migrate_if_needed()` runs once, in `main()` (~line 1284)
**before** `JarvisUI` is constructed. Guards on `Core/Identity.md` already
existing (idempotent — safe to call every launch). If found, converts old
`config/preferences.json` into `Settings.md` + `Topics/*.md`, and old
`memory/long_term.json` into `Core/Identity.md`/`Core/Preferences.md` +
`People`/`Projects`/`Facts` notes (preserving each fact's original
`updated` date), then renames both old files to `.bak` — **never
deletes**. A fresh install just gets an empty vault skeleton
(`onboarded: false`), same as the old first-run flow.

**Concurrency**: `_read_note`/`_write_note` internal helpers parse/write
the `---\n<yaml>\n---\n<body>` format with a temp-file +
`os.replace()` swap, so a write is atomic even if the real Obsidian app
has the vault open at the same time. Not stress-tested on Windows
specifically — flag if file-lock issues show up there.

**Known gap, not yet fixed**: `memory/long_term.json` was tracked in git
before this rewrite (personal data committed to history).
`.gitignore` now covers `config/preferences.json*` / `memory/
long_term.json*` / `config/vault_path.json` going forward, but no `git rm
--cached` / history cleanup has been done — the old file's git history
still needs a separate pass if that matters.

- **`memory/config_manager.py`** — `config/api_keys.json` (gitignored).
  API keys (Gemini/OpenAI/Anthropic) and selected AI provider.
  `CONFIG_DIR` here is the shared constant other modules import for the
  `config/` directory location (`vault_manager.py` imports `CONFIG_DIR`
  and `BASE_DIR` from here rather than re-deriving them).
- **`config/__init__.py`** — OS detection only (`is_windows()`/`is_mac()`/
  `is_linux()`), reads `os_system` from `api_keys.json` with a
  `platform.system()` fallback. Used throughout `actions/` for OS-specific
  code paths.

## LLM providers

- **`core/cloud_llm.py`** — one-shot (non-streaming, non-live) text/vision/
  audio-transcript calls to Gemini/OpenAI/Anthropic, used by tool actions
  that need an LLM call outside the live voice session (e.g.
  `code_helper.py`, `file_processor.py`, `flight_finder.py`'s scrape
  parsing). `get_provider()` reads the configured provider;
  `_model_for(provider, role)` maps a logical role (fast/quality/vision) to
  a concrete model name per provider.
- **`core/llm_client.py`** — a **separate, local-Ollama-oriented** client
  (`ensure_ollama_running`, `warmup_model`, streaming). Check which of
  `cloud_llm.py` vs `llm_client.py` a given action actually imports before
  assuming a change to one affects the other — they are not the same code
  path.

## Actions (tool implementations)

`actions/*.py` — one file per tool domain, each exposing the function(s)
registered in `main.py::TOOL_DECLARATIONS` + dispatched via
`_dispatch_tool()`. Notable ones:

| File | Domain |
|---|---|
| `open_app.py` | Cross-platform app launching (Windows/macOS/Linux branches) |
| `computer_control.py` / `computer_settings.py` | Screenshots, volume, WiFi, brightness, power |
| `file_processor.py` | Read/summarize/transform dropped or referenced files |
| `file_controller.py` | Safe file-system ops scoped to Desktop/Downloads/Documents/Pictures (`_is_safe_path`) |
| `browser_control.py` | URL open/navigate, real browser profile detection per-browser |
| `desktop.py` | Wallpaper + Gemini-generated one-off desktop automation scripts (sandboxed exec) |
| `dev_agent.py` | Autonomous "write and run code" agent tier — has its own error-classification/retry logic |
| `code_helper.py` | Inline code review/generation, single-shot (not autonomous like dev_agent) |
| `screen_processor.py` | Camera/screen capture + its own independent Gemini Live vision session (see above) |
| `system_monitor.py` | CPU/RAM/GPU/temp polling, feeds `ui.py`'s `_SysMetrics`/`MetricBar` |
| `proactive.py` | `ProactiveEngine` — idle-timeout check-ins, no hardcoded rules (model decides) |
| `web_search.py` | Gemini-grounded search first, DuckDuckGo fallback |
| `weather_report.py`, `flight_finder.py`, `youtube_video.py`, `reminder.py`, `game_updater.py`, `send_message.py` | Self-explanatory single-domain tools |

Convention: most files have `_get_os()`/`_base_dir()` helpers duplicated
locally rather than importing `config`'s versions — this is existing
repo style, not an oversight; don't "fix" it as a drive-by refactor.

## Dashboard / remote control

- **`dashboard/server.py`** — FastAPI app, `DashboardServer` class. Serves a
  local HTTPS (self-signed certs in `config/certs/`) web UI so a phone can
  pair (QR code via `qrcode[pil]`), stream mic audio over `/ws/phone-audio`,
  send text commands (`/api/command`), and upload files. Session auth via
  AES (`_derive_key`/`_decrypt_cbc`) keyed off a per-launch session key
  generated in `main.py` (`_make_remote_key`). `/ws` is the main
  bidirectional channel for the desktop UI's own websocket needs;
  `/ws/phone-audio` is phone-specific.

## Build & packaging

- `mark48.spec` (Windows) / `mark48-mac.spec` (macOS) — PyInstaller specs.
  **Do not bundle `config/api_keys.json`, `config/vault_path.json`, or
  `config/certs/`** — those are per-user runtime data, explicitly excluded
  in the spec's `datas` comment. The Obsidian vault itself
  (`~/Documents/JarvisVault` by default) lives outside the app entirely,
  so it never needs bundling or exclusion here either.
- `installer.iss` — Inno Setup script (Windows installer wrapper).
- `scripts/build_dmg.sh` — macOS DMG packaging.
- `.github/workflows/build-windows.yml` / `build-macos.yml` — CI build
  pipelines.
- `requirements.txt` has a flagged note: `google-generativeai` appears
  unused (only `google-genai` is actually imported) — confirm before
  removing, don't assume the note is stale without re-grepping.

## Known gotchas (found the hard way — re-check before assuming otherwise)

1. **Lazy imports don't cross method boundaries.** `core/live_voice.py`
   imports `google.genai.types` locally inside each method that needs it.
   A previous bug: `_receive_audio()` used `types.FunctionResponse(...)`
   without its own local import (only the sibling `run()` method had one),
   causing a `NameError` that crashed the whole `asyncio.TaskGroup` on
   every tool call. If you add a method using `types`, import it there too.
2. **Overlay widgets must be explicitly torn down.** Swapping
   `MainWindow._overlay` to a new overlay without calling `hide()` +
   `deleteLater()` on the old one leaves it alive underneath, which looked
   like "the setup menu won't close." Always route overlay transitions
   through `_close_overlay()`.
3. **`language_name("auto")` is truthy.** Never gate "is a language locked"
   on `if language_name(code):` — check `code != "auto"` explicitly.
4. **System prompt instruction precedence is positional.** The
   `[LANGUAGE OVERRIDE]` block works by being appended *after*
   `core/prompt.txt`'s conflicting per-turn language-detection rule, not by
   editing prompt.txt. If you need another hard override, follow the same
   pattern (append last, word it as explicitly taking priority) rather than
   trying to edit the base prompt's conditional logic.
5. **Two separate Gemini Live sessions exist** — the main conversation
   (`core/live_voice.py` via `main.py`) and vision narration
   (`actions/screen_processor.py`). A preference or fix applied to one does
   **not** automatically apply to the other; check both when the request is
   about "voice," "the live session," or delivery (accent/style/pace)
   generically. `screen_processor.py` keeps its own copy of every one of
   these lookups (voice, `[DELIVERY OVERRIDE]` construction, and the
   `thinking_config` fix in gotcha 10) rather than sharing code with
   `core/live_voice.py` — this has bitten every voice-related feature added
   so far, not just voice_name originally.
6. **`macOS` lacks GNU `timeout`.** For scripted/background verification
   launches, run `python main.py > log 2>&1 &`, sleep, check the log, then
   `kill` the PID — don't rely on `timeout` being available.
7. **Gemini has two unrelated audio-generation code paths — don't reuse one
   for the other.** `GeminiLiveSession` (`core/live_voice.py`) is a
   long-lived bidirectional `client.aio.live.connect()` session with the
   voice locked in at connect time; there's no way to change voice or say
   an arbitrary one-off line mid-session. `core/voice_preview.py` is the
   single-turn `client.models.generate_content(response_modalities=
   ["AUDIO"], ...)` endpoint — no session, no mic, just text-in/audio-out.
   Needing "say X in voice Y right now" (previews, one-off announcements)
   means the one-shot endpoint, not threading a fake turn through the live
   session.
8. **The voice preview's `sd.play()` and the live session's persistent
   `sd.RawOutputStream` (`GeminiLiveSession._play_audio()`) are two
   independent CoreAudio/PortAudio streams on the same output device.**
   When both are active at once — preview firing while Jarvis is mid-
   response, or the mic picking up the preview and feeding it back in —
   playback audibly degrades into static/glitching. Confirmed by isolating
   the decoded PCM (clean via `afplay`) from `sd.play()` in-app (glitchy
   when overlapping). `MainWindow._show_preferences()` force-mutes the mic
   for the panel's lifetime as a mitigation; it does not stop a live
   session speaking at the exact moment a preview starts. If static
   resurfaces specifically during that overlap, the real fix is routing
   preview audio through the same output stream instead of opening a
   second one, not more mute logic.
9. **Free-tier TTS-preview quota is a hard 10 requests/day total, plus a
   stacked 3-requests/minute cap — and each model tracks its own separate
   bucket.** Confirmed directly against the API: `gemini-2.5-flash-preview-tts`
   burst calls returned `429 RESOURCE_EXHAUSTED` with
   `quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier,
   quotaValue: 10` (and separately `GenerateRequestsPerMinutePerProjectPerModel-
   FreeTier, quotaValue: 3`). No amount of client-side pacing/backoff works
   around the daily cap — this is why `core/voice_preview.py` bundles
   pre-generated clips instead of synthesizing on demand (see above). The
   daily cap also behaves like a **rolling window, not a midnight reset** —
   quota freed up gradually the next day rather than all at once.
   `core/voice_preview.py` migrated to `gemini-3.1-flash-tts-preview` once
   2.5's quota was exhausted, and that model turned out to track quota in
   a **completely separate bucket** — it succeeded immediately while 2.5
   was still fully exhausted, which is as much why the migration happened
   as the model being newer. Also confirmed
   `gemini-2.5-flash-native-audio-preview-*` (the Live API model) can't
   substitute for the TTS-preview endpoint regardless: calling
   `generate_content` with it 404s — `"not supported for generateContent"`
   — it only works through `client.aio.live.connect()`'s bidirectional
   streaming, which shares quota with actual conversations rather than
   having its own bucket.
10. **`GeminiLiveSession`/`screen_processor.py`'s Live config needs
    `thinking_config=types.ThinkingConfig(thinking_budget=0)`, or the model
    can silently return zero audio.** Found by accident while regression-
    testing an unrelated SDK upgrade: a plain text turn sent to
    `gemini-2.5-flash-native-audio-preview-12-2025` with
    `response_modalities=["AUDIO"]` came back with only `text`/`thought`
    parts and **no `inline_data`/audio part at all** — reproduced
    identically on both `google-genai` 2.10.0 and 2.12.0, so it's a model-
    default-behavior issue, not an SDK bug. Setting `thinking_budget=0`
    fixed it immediately (verified against the real
    `GeminiLiveSession._build_config()`, not just an isolated test). Both
    `core/live_voice.py` and `actions/screen_processor.py` now set this —
    per gotcha 5, check both if audio silently stops working again.
11. **`gemini-3.1-flash-live-preview` (now the Live conversation model —
    `core/live_voice.py::GeminiLiveSession.LIVE_MODEL` and
    `actions/screen_processor.py::_LIVE_MODEL`) needs two config/call-shape
    changes vs 2.5, or `send_client_content()` hard-closes the socket with
    `APIError 1007: Request contains an invalid argument`.** This was
    originally believed to be an unfixable backend incompatibility (see
    prior version of this gotcha) — it is not; the actual requirements,
    found by reading Google's live-guide docs plus direct SDK/API testing,
    are:
    1. `LiveConnectConfig` must set
       `history_config=types.HistoryConfig(initial_history_in_client_content=True)`.
       Despite the docs implying this only permits a single "seed the
       initial history" call, it was verified empirically (multiple
       `send_client_content()` calls in one session, including interleaved
       tool calls and image turns) to work for the entire session, not
       just once.
    2. Every `send_client_content(turns={...})` call must include
       `"role": "user"` in the `turns` dict — omitting it 1007s even with
       `history_config` set. The 2.5 model never required this.
       `GeminiLiveSession.send_text()`/`send_image_turn()` and
       `screen_processor.py`'s `_send_loop()` all set it now.
    - **Do not use `send_realtime_input()` as a substitute for
      `send_client_content()` on this model** — it was tried first (per
      the docs' general "use `send_realtime_input` for ongoing turns"
      guidance) and has two problems specific to this app's usage: (a)
      `send_realtime_input(media=...)` — used for streaming mic audio in
      `_send_realtime()` — 1007s outright (`"media_chunks is
      deprecated"`); fixed by using `audio=...` instead, which does work
      and is the one `send_realtime_input()` change that *is* still in
      place. (b) `send_realtime_input(video=...)`, the documented
      replacement for sending images, connects and doesn't error, but
      **silently fails to deliver the image to the model** — verified by
      sending solid-color test images (green/blue/yellow) and getting
      wrong colors back every time via `video=`, vs. the correct color
      every time via `send_client_content()` with `inline_data` + `role:
      "user"`. Root cause not identified beyond "the model behaves as if
      it received no image" — avoid `send_realtime_input(video=...)` for
      anything vision-related on this model.
    - Verified end-to-end against the real `GeminiLiveSession` class (not
      just isolated API calls): plain text turns, tool-call turns, and
      image+text turns (`send_image_turn`) all work correctly and
      repeatably within one persistent session, with the full production
      config (`tools`, `system_instruction`, `thinking_config`,
      `speech_config` all set together).
