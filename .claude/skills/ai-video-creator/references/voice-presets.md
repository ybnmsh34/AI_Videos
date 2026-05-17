# Voice presets (edge-tts)

The skill uses **edge-tts** — Microsoft's neural voices via the Edge browser API. Free, no key, very high quality.

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
