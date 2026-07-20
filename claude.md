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

- **`ui.py`** — PyQt6 GUI shell (~2200 lines, single file — shrank from
  ~3600 when the HUD moved to HTML/CSS/JS, see "Web-based HUD" below).
  Structural map:
  - `JarvisUI` (~line 2058) — thin facade `main.py` and every `actions/*`
    module talk to (`muted`, `current_file`, `on_text_command`,
    `write_log`, `set_state`, `show_content`, `is_ready`, etc.); wraps
    `MainWindow`. **This facade's public surface did not change** in the
    QWebEngineView migration — only `MainWindow`'s internals did — so
    nothing in `actions/` needed touching.
  - `MainWindow` (~line 1285) — the actual `QMainWindow`. Its central
    widget is now a `QWebEngineView` (see "Web-based HUD" below); it also
    owns overlay lifecycle (setup/onboarding/remote-QR/camera windows) and
    the header ⚙ **Preferences** trigger (now a gear icon inside the web
    page, wired via the bridge — not a native `QPushButton` anymore).
    Thread-safe UI updates still go through `pyqtSignal`s (`_log_sig`,
    `_state_sig`, `_content_sig`, `_reconfig_sig`, `_cam_frame_sig`, etc.)
    since voice/tool work runs off the Qt thread — these now feed into
    `ui_web_bridge.py::Bridge`'s `push_*()` methods instead of mutating
    native widgets directly.
  - `SetupOverlay` (~line 412) — first-run API-key/provider setup screen.
  - `OnboardingOverlay` (~line 642) — first-run **and** reopenable
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
  - `RemoteKeyOverlay` (~line 1057) — remote/QR pairing window.
  - `_CameraPreview` (~line 285) / `_CameraStreamWindow` (~line 352) —
    native camera snapshot preview and live-stream panel; unchanged from
    the pre-redesign implementation (reuses `actions/screen_processor.py`'s
    `_cam_loop` as-is).
  - **All five of the above are top-level floating windows, not
    widgets stacked under `centralWidget()`** — `_make_floating()`
    (~line 1690) applies `Qt.WindowType.Window | FramelessWindowHint |
    WindowStaysOnTopHint` (+`Tool` for the camera preview) and
    `WA_TranslucentBackground`. This is a deliberate consequence of the
    QWebEngineView migration: child-widget compositing over a
    `QWebEngineView` is unreliable in Qt (a known limitation), so every
    overlay/dialog became a genuine top-level window instead, repositioned
    off `self.geometry()` (screen coordinates) in `resizeEvent`/
    `moveEvent` via `_reposition_floats()` rather than parent-local
    coordinates.
  - `_close_overlay()` helper on `MainWindow` — **always** call this before
    swapping `self._overlay` to a new overlay. See gotcha below.
  - `_browse_for_file()` (~line 1829) — native `QFileDialog.getOpenFileName`
    triggered by the web page's paperclip/attach icon via
    `Bridge.requestFileDialog()`. Drag-and-drop is separate and native:
    `MainWindow.dragEnterEvent`/`dropEvent` are wired directly on the
    window itself (not a transparent overlay widget — simpler and avoids
    `WA_TransparentForMouseEvents` potentially also blocking drop
    delivery), both paths funnel into `_on_file_selected(path)`.
  - `_SysMetrics` — live CPU/RAM/GPU/temp telemetry polling (still native
    Python/Qt); it feeds the web HUD's stat tiles via `statsUpdated`, see
    below.
  - **Deleted in the redesign, do not go looking for these**: `HudCanvas`,
    `MetricBar`, `LogWidget`, `FileDropZone`, `_DropCanvas` — the HUD
    canvas/waveform, metric bars, log panel, and drag-drop widget were all
    native `QWidget`/`QPainter` code, fully replaced by the HTML/CSS/JS
    page below. `actions/file_processor.py` still receives files the same
    way (via the `JarvisUI` facade), it just no longer has a
    `FileDropZone` backing it.

### Web-based HUD (`ui_web/`)

The entire HUD surface — waveform/head visualization, log panel, header
buttons, command row (mic/interrupt/remote/attach/send), stat tiles — is
now a single HTML/CSS/JS page, **not** native PyQt widgets. `MainWindow`
(`ui.py` ~line 1285) just hosts a `QWebEngineView` pointed at
`ui_web/index.html` (loaded via `QUrl.fromLocalFile`, so relative asset
paths resolve normally) and bridges to it with a `QWebChannel`.

- **`ui_web/index.html`** — DOM structure. Buttons that need a crisp icon
  use **inline SVG** (`viewBox="0 0 24 24" fill="none" stroke="currentColor"`,
  `stroke-width` 1.6–1.8), not CSS-drawn shapes or emoji — see `#prefsBtn`
  (gear), `#attachBtn` (paperclip), `#muteBtn` (mic). This is the
  established convention for any new icon button in this file; prefer it
  over hand-built div/border shapes (the mute button was originally a
  CSS ring+diagonal-slash div and was replaced with a proper Feather-style
  mic SVG for exactly this reason — plain borders read as an abstract
  "no" icon, not a microphone). `currentColor` is what lets `color`
  changes (e.g. `#muteBtn.muted` turning red) restyle the icon without
  touching the SVG itself.
- **`ui_web/hud.css`** — all styling. `.circle-btn` (56px, `border-radius:
  50%`, flex-centered) is the shared shell for the mic/interrupt/remote
  buttons in `#commandRow`; icon-specific sizing/color rules live under an
  `#idSelector` block per button, generally near the bottom of the file
  (search for the button's `id`, not a class, since most command-row
  icons are one-offs).
  - **Pattern: hide (don't remove) a button that still has live JS
    wiring.** To hide `#remoteBtn` without touching `hud.js` (which holds
    a `$('#remoteBtn')` reference, a `click` listener calling
    `bridge.clickRemote()`, and a `bridge.remoteConnected` signal handler
    that toggles a `.connected` class on it), the fix was a single
    `#remoteBtn { display: none; }` rule in `hud.css`, leaving the
    element and all JS untouched. Removing the element from `index.html`
    instead would throw on `$('#remoteBtn')` being `null` the moment
    `hud.js` tries to `addEventListener` on it — `hud.js` doesn't
    null-guard any of its `els.*` lookups.
  - Mute button's muted-state slash is a `<line class="mute-slash">`
    inside the SVG, toggled via `#muteBtn.muted .mute-slash { display:
    inline; }` (SVG children default to `display: none` only when
    explicitly set — plain CSS `display` works fine on SVG `<line>` in
    Chromium/QtWebEngine).
- **`ui_web/hud.js`** — single IIFE, no framework. `els` (top of file) is
  a flat `id → element` lookup table built once via `document.querySelector`
  with **no null-checks** — adding a button to `index.html` without a
  matching `els.foo: $('#foo')` entry (or vice versa) fails loudly at
  first use, not silently. State (`muted`, `rightOpen`, `activity`, `log`)
  is a plain object mutated directly, not reactive — every state change
  has a matching explicit `render*()`/`apply*()` call right next to it.
  - **Qt↔JS bridge**: `connectBridge()` opens a `QWebChannel` and binds
    `channel.objects.bridge` (the Python-side `QObject` exposed by
    `ui.py`) to the local `bridge` var. Python→JS is Qt signals
    (`logAppended`, `stateChanged`, `mutedChanged`, `statsUpdated`,
    `remoteConnected`) connected to `hud.js` handlers; JS→Python is plain
    method calls on `bridge` (`sendText`, `toggleMute`, `clickInterrupt`,
    `clickRemote`, `requestFileDialog`, `openPreferences`,
    `toggleFullscreen`, `requestSync`). If
    `QWebChannel`/`qt.webChannelTransport` isn't present (e.g. the page
    opened directly in a regular browser for CSS/layout iteration, as
    opposed to inside the app), `connectBridge()` falls back to
    `runPreviewMode()` — dummy data, no Python calls — which is what makes
    it safe to open `ui_web/index.html` standalone in a browser to preview
    a CSS/markup change without booting the whole app.
  - Keyboard shortcuts (F4 mute, F11 fullscreen, Esc interrupt) are
    handled **in JS**, not as native `QShortcut`s on `MainWindow` — a
    `QWebEngineView` owning keyboard focus
    swallows native shortcuts (Chromium-embedding quirk), so they're
    forwarded to `bridge` from a `window.addEventListener('keydown', ...)`
    here instead.

### Glass design system — `ui_web/hud.css` palette, and where it leaks into native Qt

The redesign ("new ui" commit) established a dark-navy/cyan **glass** look:
translucent panels (`background: rgba(15,32,52,0.55)` + `backdrop-filter:
blur(28px) saturate(1.6)`), a `rgba(120,210,255,0.26)` hairline border,
22px corner radius, and a `#4fd8ff` accent (`hud.css`'s `.glass` class,
`:root { --pbg; --pblur; --pbd; }`). Body font is `IBM Plex Mono`
(`hud.css` `@font-face`, `ui_web/fonts/*.woff2`), not a system font.

**Only one native Qt surface still needs to visually match this palette:
`OnboardingOverlay` (`ui.py`)** — the Preferences panel opened via the ⚙
button (`#prefsBtn` → `bridge.openPreferences()` → `MainWindow._show_preferences()`).
It's a real `QWidget`, not part of the web page, so it can't use `hud.css`
directly or get actual `backdrop-filter` blur (Qt stylesheets have no
equivalent — the "glass" look here is approximated with a near-opaque
tinted background, not real blur-through). `SetupOverlay` and
`RemoteKeyOverlay` are the other native overlays but were **not** ported
to this palette (still on the old flat-black/`C.PRI` cyan retro-terminal
look from before the redesign) — deliberate scope cut, not an oversight;
redo them the same way if full consistency is ever wanted.

- **`class G` (`ui.py`, right after `class C`)** — the glass palette,
  hand-translated from `hud.css`'s CSS-alpha (`rgba(r,g,b,0–1)`) to Qt
  stylesheet syntax (`rgba(r,g,b,0–255)`) since Qt's `rgba()` alpha channel
  is 0–255, not a 0–1 fraction — copying a `hud.css` value verbatim
  without converting the alpha will silently render far more opaque/
  transparent than intended. `G.PANEL_BG`/`G.FIELD_BG` are intentionally
  **more opaque** than `hud.css`'s `--pbg` (near-black, alpha ~250/255)
  rather than matching its ~0.55 alpha — with no real blur behind it, a
  CSS-accurate translucency read as low-contrast/hard-to-read text over
  whatever the floating window happened to be layered on, so the native
  version leans darker/near-opaque purely for legibility, breaking strict
  palette fidelity on purpose. If `hud.css`'s panel alpha values change,
  don't blindly re-sync `G`'s alphas to match — re-check readability first.
- Only `OnboardingOverlay` was repainted with `G.*`; `class C` (the old
  palette) is still very much alive and used by `SetupOverlay`,
  `RemoteKeyOverlay`, `_CameraPreview`, `_CameraStreamWindow`, and
  `_SysMetrics` — don't assume `G` superseded `C`, they coexist by design
  (one native surface on the new palette, several others still on the old
  one).
- `OnboardingOverlay` is a real floating top-level window (`_make_floating()`,
  `WA_TranslucentBackground` + frameless + always-on-top), not a child
  widget stacked over the `QWebEngineView` — native child widgets don't
  reliably composite on top of a `QWebEngineView`'s own GPU surface, so
  every overlay in this file (`SetupOverlay`, `OnboardingOverlay`,
  `RemoteKeyOverlay`) went through this conversion when the web HUD landed.

**Avengeance/"Avengers" font pack — removed.** `Plans/avengeance-fonts.md`
documents the original introduction; `core/fonts.py` now just sets
`DISPLAY_FAMILY`/`HEADER_BOLD_FAMILY`/`HEADER_FAMILY` to `""` (Qt's
default-application-font sentinel) and `load_fonts()` is a no-op — kept
only so `ui.py`'s one `jfonts.load_fonts()` call site and every existing
`QFont(jfonts.X_FAMILY, ...)` call site don't need touching if a custom
font is ever reintroduced. `assets/fonts/avengeance/` (and the now-empty
`assets/` tree) and the matching `datas` entries in both PyInstaller specs
are gone. The dev-only `FontDebugDialog` (`ui.py`) and its
`MainWindow._show_font_debug()` existed solely to preview that pack and
were deleted outright — **this also required removing the `showFontDebug`
`pyqtSlot` from `ui_web_bridge.py::Bridge` and the `Ctrl+Shift+F` handler
in `ui_web/hud.js`'s keydown listener**, since those called into the now-
deleted method; the JS-side wiring is easy to miss when deleting a
Python-side dev feature because `hud.js`'s bridge calls don't get caught
by a Python-only grep for the deleted method name.

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
  local **plain HTTP** (deliberately — see gotcha 13) web UI on port 8000 so
  a phone can pair (QR code via `qrcode[pil]`), stream mic audio over
  `/ws/phone-audio`, send text commands (`/api/command`), and upload files.
  Session auth via AES (`_derive_key`/`_decrypt_cbc`) keyed off a per-launch
  session key generated in `main.py` (`_make_remote_key`) — this is what
  actually protects command confidentiality, independent of transport.
  `/ws` is the main bidirectional channel for the desktop UI's own
  websocket needs; `/ws/phone-audio` is phone-specific. `get_url()` /
  `get_manual_url()` both point at the same host:port (`get_manual_url()`
  is just the bare `ip:port` form for typing into a browser, since there's
  only one scheme now — no separate HTTPS alias port).

## Build & packaging

- **`scripts/build_mac.sh`** — one-shot macOS build: activates `.venv` if
  present, runs `pyinstaller mark48-mac.spec`, then `scripts/build_dmg.sh`.
  Produces `installer_output/JARVIS-Setup.dmg`. Must run on macOS.
- **`scripts/build_windows_ci.sh [version]`** — triggers the Windows build
  via GitHub Actions (`gh workflow run build-windows.yml`) rather than
  building locally, since PyInstaller can't cross-compile a Windows exe
  from macOS. Prints the `gh run watch` / `gh run download` follow-up
  commands. Requires `gh` authenticated against the repo.
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
12. **Search recency is a `system_instruction` problem, not just a
    grounding problem — always pair `google_search` with a date-anchor
    instruction.** `google_search` grounding fetching live results does
    NOT by itself guarantee the model's synthesis of those results reads
    as current — without being explicitly told today's real date and that
    live grounding should override its training-era assumptions, the
    model can still misdate things or blend in stale background knowledge
    on top of fresh search hits. `actions/web_search.py::_recency_instruction()`
    is the fix — a `system_instruction` string (real date + "trust
    grounding over training data, prioritize recency") passed alongside
    `tools: [{"google_search": {}}]` in every grounded call
    (`_gemini_search()`, used by `search`/`news`/`research`/`price`/
    `compare`, and `_gemini_headlines()`). **This is a standing
    convention, not a one-off fix** — any new tool that adds
    `google_search` grounding must include this instruction too, or it
    will regress to feeling stale even though the underlying grounding
    still works. Separately, `core/prompt.txt`'s "Time-sensitive info"
    rule stops the *live conversation model* from skipping `web_search`
    entirely and answering time-sensitive questions from its own memory —
    a distinct failure mode from the grounded call itself being
    under-anchored, and both were needed to fix the user-reported
    "stale news" symptom.
13. **The dashboard used to switch to HTTPS-only whenever
    `config/certs/jarvis.{key,crt}` happened to exist on disk, and that
    silently broke both connection paths.** `dashboard/server.py` no
    longer has this branch at all — it always serves plain HTTP on a
    single port (`PORT = 8000`). Found by direct reproduction: with the
    certs present, `_ssl_enabled()` returned `True`, which (a) made
    `get_manual_url()` return a bare `ip:8001` string with no scheme,
    pointing at a TLS-only alias port — typing that into a browser sends
    plain HTTP, which a TLS listener just drops (`curl` confirmed "Empty
    reply from server"), and (b) made the QR code's `https://ip:8000/...`
    link hit a self-signed cert, which phone browsers show as a
    connection-not-private interstitial instead of the app — both looked
    like "goes to the URL, nothing happens." Deliberately not re-added:
    the file's own header docstring already stated the plain-HTTP design
    intent, and command confidentiality is handled at the application
    layer (AES, `_derive_key`/`_decrypt_cbc`) independent of transport, so
    TLS was redundant for that path anyway — it only mattered for
    `/ws/phone-audio` mic streaming and `/api/upload` file transfers,
    which do travel in cleartext now. That's an accepted tradeoff for a
    LAN-only personal-use feature, not an oversight — if it ever needs
    revisiting, don't just drop the certs back in without also fixing
    `get_manual_url()`/the alias-port split, since that pairing is what
    actually broke it.

14. **`requirements-freeze.txt` (what the Windows CI build actually
    installs) can silently drift from `requirements.txt` and `mark48.spec`'s
    `hiddenimports`.** Shipped a Windows build that crashed on launch with
    `ModuleNotFoundError: No module named 'PyQt6.QtWebEngineWidgets'` even
    though `mark48.spec`'s `hiddenimports` correctly listed
    `PyQt6.QtWebEngineWidgets`/`QtWebEngineCore`/`QtWebChannel` — the spec's
    hidden-import list only tells PyInstaller to bundle a module *if it's
    installed in the build env*; `requirements-freeze.txt` had `PyQt6` but
    not `PyQt6-WebEngine`, so the package was never installed in CI in the
    first place, and PyInstaller silently omitted it (no build-time error).
    Fixed by adding `PyQt6-WebEngine` to `requirements-freeze.txt`. When
    adding a new dependency that the packaged Windows build needs, update
    `requirements-freeze.txt` too, not just `requirements.txt` — they are
    not kept in sync automatically and CI only reads the freeze file (see
    `scripts/build_windows_ci.sh` / `.github/workflows/build-windows.yml`).
15. **`installer.iss`'s `AppId` GUID must be rotated whenever the app is
    renamed/rebranded, or Windows installs keep landing in the old app's
    folder forever.** When the app was renamed `MARK XLVIII` → `JARVIS`
    (commit `634bb26`), `DefaultDirName` was updated
    (`{localappdata}\Programs\MarkXLVIII` → `...\Programs\JARVIS`) but the
    `AppId` GUID was left unchanged. Inno Setup keys its uninstall/upgrade
    registry entry (`HKCU\...\Uninstall\{AppId}_is1`, "Inno Setup: App
    Path") purely by `AppId`, and every install sharing that GUID reuses
    the path recorded there — on any machine that had ever run the old
    MarkXLVIII-branded installer, subsequent JARVIS-branded installs
    silently reinstalled into the stale `...\Programs\MarkXLVIII` path
    instead of the new `DefaultDirName`, and the app's own `ui_web` HUD
    assets weren't present there (predates the web-HUD rewrite), producing
    a QWebEngineView "file may have moved" error at launch. This persisted
    even after uninstalling through Windows Settings and manually deleting
    the folder — deleting the folder doesn't guarantee the registry
    App-Path association clears. Fixed by rotating to a fresh `AppId`
    (`C42C19AC-6121-427A-B51D-8F43FD863E48`), which severs the link
    entirely and forces a clean install at the current `DefaultDirName`.
    Any future rename/rebrand of this app needs the same treatment: change
    `AppId`, not just `MyAppName`/`DefaultDirName`. Affected machines with
    a pre-rotation install still need the leftover `...\Programs\MarkXLVIII`
    folder (and ideally the old registry key,
    `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{B1F2C6A0-6C1E-4C7B-9C7A-6C6D3D6E9A48}_is1`)
    removed manually once — the new GUID means it'll never self-heal via
    reinstall.

PUT ANY PLANS YOU MAKE INTO THE PLANS FOLDER
WHEN BUGFIXING: ADD DEBUG LOGS IF THE INPUT/PROBLEM IS UNCLEAR, REMOVE WHEN DONE BUGFIXING