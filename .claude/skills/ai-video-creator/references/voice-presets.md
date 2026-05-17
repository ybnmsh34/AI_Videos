# Voice presets

The skill picks a voice from `meta.voice.voice_id` in the storyboard. TTS chain:

1. **edge-tts** (default, online) — Microsoft Edge neural voices. Free, no key, very high quality.
2. **Piper** (offline fallback) — local CPU TTS, runs without internet. Voice models auto-downloaded on first use to `voices/`.

If edge-tts fails (no internet, endpoint down) the renderer falls back to Piper automatically. Force Piper with `OFFLINE_TTS=1`.

List all available voices:
```bash
edge-tts --list-voices
```

## Recommended voice IDs by vibe

| Vibe | Voice ID | Notes |
|---|---|---|
| Warm energetic female (default) | `en-US-AriaNeural` | Lively, modern, all-purpose |
| Calm female narrator | `en-US-JennyNeural` | Documentary feel |
| Friendly upbeat male | `en-US-GuyNeural` | Clear, approachable |
| Deep authoritative male | `en-US-DavisNeural` | Trailer voice |
| Playful character / kid | `en-US-AnaNeural` | High-energy, animated |
| Documentary narrator | `en-US-TonyNeural` | Measured, gravitas |
| British female | `en-GB-SoniaNeural` | Sophisticated |
| British male | `en-GB-RyanNeural` | BBC-style |
| Australian female | `en-AU-NatashaNeural` | Friendly, casual |
| Spanish (Mexico) female | `es-MX-DaliaNeural` | For Spanish content |
| French female | `fr-FR-DeniseNeural` | For French content |

Set the chosen voice in `storyboard.json` under `meta.voice.voice_id`.

## Rate, pitch, volume tweaks

edge-tts supports inline SSML-style adjustments via render.py args:

```json
"voice": {
  "voice_id": "en-US-AriaNeural",
  "rate": "+0%",
  "pitch": "+0Hz",
  "volume": "+0%"
}
```

- `rate`: `-50%` to `+200%` (negative = slower)
- `pitch`: `-50Hz` to `+50Hz`
- `volume`: `-50%` to `+50%`

For cartoons/kids' content, try `rate: "+10%"` and `pitch: "+5Hz"` for extra liveliness. For documentary, `rate: "-5%"` slows for gravitas.

## Piper voices (offline fallback)

The renderer maps each edge-tts voice to the closest Piper voice automatically. You don't need to set this manually unless you want a specific Piper voice.

| edge-tts voice | Piper fallback |
|---|---|
| `en-US-AriaNeural`, `en-US-JennyNeural` | `en_US-amy-medium` |
| `en-US-GuyNeural`, `en-US-DavisNeural`, `en-US-TonyNeural` | `en_US-ryan-medium` |
| `en-US-AnaNeural` | `en_US-amy-low` |
| `en-GB-SoniaNeural`, `en-AU-NatashaNeural` | `en_GB-jenny_dioco-medium` |
| `en-GB-RyanNeural` | `en_GB-alan-medium` |

Browse all Piper voices: https://huggingface.co/rhasspy/piper-voices

Piper voices are ~50MB each, downloaded once and cached in `.claude/skills/ai-video-creator/voices/`. Quality tiers: `x_low` < `low` < `medium` < `high` (file size and CPU cost increase with quality).

