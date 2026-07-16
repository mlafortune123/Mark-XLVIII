"""scripts/generate_voice_previews.py — one-time (re-)generation of the
bundled voice-preview clips in core/voice_previews/*.wav.

Run this whenever core/voices.py::SUPPORTED_VOICES changes (a voice added,
removed, or renamed) so the shipped bundle stays in sync — see
core/voice_preview.py for why these are bundled instead of synthesized live
on every dropdown click (the TTS-preview model's quota is tight).

Usage:
    python scripts/generate_voice_previews.py [--force]

Requires a configured Gemini API key (same one the app uses, read via
memory/config_manager.py). Resumable: existing files are skipped unless
--force is passed. Paces requests to stay under the TTS-preview model's
per-minute quota (3/min on free tier). Free tier also caps this model at
10 requests/day *total*, which pacing can't work around — on a free-tier
key, expect a single run to only get partway through all 30 voices before
hitting 429s; just re-run the script again once the daily quota resets to
pick up where it left off.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.voices import SUPPORTED_VOICES
from core.voice_preview import synthesize, write_wav
from memory.config_manager import get_gemini_key

OUT_DIR = Path(__file__).resolve().parent.parent / "core" / "voice_previews"
# Free tier stacks a 3-requests/minute cap on top of the 10/day one (confirmed
# via 429 quotaId=GenerateRequestsPerMinutePerProjectPerModel-FreeTier,
# quotaValue=3). 4s spacing fires ~15/minute and burns most of a run's
# attempts on minute-throttling instead of the day's actual budget; 21s
# keeps every request under the 3/min cap so a run only ever stops on the
# daily limit, not a wasted minute-window collision.
_REQUEST_SPACING_SECONDS = 21


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                         help="Regenerate even if a clip already exists.")
    args = parser.parse_args()

    api_key = get_gemini_key()
    if not api_key:
        print("No Gemini API key configured (config/api_keys.json). Aborting.")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    todo = [name for name, _style in SUPPORTED_VOICES
            if args.force or not (OUT_DIR / f"{name}.wav").exists()]
    if not todo:
        print(f"All {len(SUPPORTED_VOICES)} voices already bundled in {OUT_DIR}. "
              "Pass --force to regenerate.")
        return 0

    print(f"Generating {len(todo)}/{len(SUPPORTED_VOICES)} voice(s) into {OUT_DIR} ...")
    failures = []
    for i, name in enumerate(todo):
        try:
            audio_bytes, sample_rate = synthesize(api_key, name)
            write_wav(OUT_DIR / f"{name}.wav", audio_bytes, sample_rate)
            print(f"  [{i + 1}/{len(todo)}] {name} — ok "
                  f"({len(audio_bytes)} bytes @ {sample_rate} Hz)")
        except Exception as e:
            print(f"  [{i + 1}/{len(todo)}] {name} — FAILED: {e}")
            failures.append(name)

        if i < len(todo) - 1:
            time.sleep(_REQUEST_SPACING_SECONDS)

    if failures:
        print(f"\n{len(failures)} voice(s) failed: {', '.join(failures)}. "
              "Re-run the script to retry just those (already-generated ones are skipped).")
        return 1

    print("\nDone — all voices bundled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
