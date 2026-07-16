# Fix: accent/style/pace/language not applying to live conversation

> Updated: originally accent/style/pace only; extended to fold the
> [LANGUAGE OVERRIDE] into the same turn-injection mechanism
> (`_priming_directive()`, formerly `_delivery_directive()`) since it has
> the exact same latent bug (system_instruction-only, never re-sent on
> settings change) even though it wasn't specifically reported broken.

## Root cause (confirmed)

Accent/style/pace control on Gemini's Live API (`gemini-3.1-flash-live-preview`)
is **not documented as a `SpeechConfig`/`system_instruction` feature** the way
it is for the one-shot TTS endpoint (`gemini-3.1-flash-tts-preview`, used by
`core/voice_preview.py`). Google's own docs draw an explicit line: TTS is
"controllable... guide the style, accent, pace, and tone"; Live API is
"designed for interactive, unstructured audio" with no such claim, and the
model card for `gemini-3.1-flash-live-preview` lists no style/accent
capability at all.

However, the user confirmed empirically that **directly telling Jarvis mid-
conversation** ("can you talk with a British accent?") does work. So the
mechanism works — it's a live conversational turn, not a
`system_instruction` fed in once at connect time. The existing
`[DELIVERY OVERRIDE]` block (`main.py::_build_system_prompt`,
`actions/screen_processor.py::_session_loop`) is the wrong delivery
mechanism: it's baked into `system_instruction` at connect time, phrased as
third-person meta-description ("The user has explicitly configured..."),
and — separately — never gets re-sent when the user changes the setting in
Preferences mid-session (no reconnect wiring exists at all today).

## Fix

Stop relying on `system_instruction` alone for accent/style/pace. Instead,
**inject an explicit direct-command turn** ("Please speak with a British
accent from now on...") right after connecting, and again whenever the user
changes accent/style/pace in Preferences — the same shape of instruction
that's confirmed to work when spoken by the user.

1. `main.py`
   - Add `_delivery_directive() -> str | None`: same style/pace/accent
     lookups as today, phrased as a direct imperative instead of a
     third-person settings description.
   - `_on_voice_session_connected`: if the active backend is Gemini and a
     directive exists, send it as a turn (`send_text(..., turn_complete=True)`)
     right after connecting.
   - New `_on_settings_saved()` method: thread-safe
     (`asyncio.run_coroutine_threadsafe`, same pattern as `_on_text_command`)
     re-send of the directive to the *currently running* session — no
     reconnect needed, since this is just conversational content, not
     connection config. Wire `self.ui.on_settings_saved = self._on_settings_saved`.
   - Keep the existing `[DELIVERY OVERRIDE]` system_instruction block as
     harmless reinforcement, not the primary mechanism.

2. `ui.py`
   - Add `on_settings_saved` callback slot on `MainWindow`/`JarvisUI`,
     mirroring the existing `on_text_command` forwarding pattern.
   - `_on_preferences_saved` invokes it after `vault_manager.save_settings()`.

3. `actions/screen_processor.py`
   - Same treatment for the vision-narration session (gotcha 5: two
     independent Live sessions, fixes don't cross over automatically).

## Out of scope

- `voice_name`/`language_code` still require a full reconnect to change
  (structural connect-time config, per gotcha 7) — not addressed here.
- Not switching to a separate TTS engine (edge-tts/Piper) for real accented
  audio — direct prompt injection is confirmed sufficient.
