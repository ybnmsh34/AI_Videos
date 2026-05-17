# Storyboard JSON schema

The storyboard is the single source of truth for the renderer. Save it at `work/<slug>/storyboard.json`.

## Shape

```json
{
  "meta": {
    "title": "Octopus Explains the Tides",
    "slug": "octopus-explains-tides",
    "style": "cartoon",
    "style_suffix": "Pixar-style 3D cartoon, vibrant colors, soft lighting, friendly characters",
    "aspect_ratio": "9:16",
    "total_duration_s": 30,
    "voice": {
      "provider": "elevenlabs",
      "voice_id": "EXAVITQu4vr4xnSDxMaL",
      "stability": 0.5,
      "similarity_boost": 0.75
    },
    "music": {
      "mood": "upbeat playful",
      "volume_db": -22
    },
    "captions": {
      "enabled": true,
      "style": "tiktok-bold-white"
    }
  },
  "scenes": [
    {
      "id": "01",
      "duration_s": 5,
      "narration": "Meet Otto, an octopus who's about to teach you why the ocean breathes.",
      "image_prompt": "A cheerful purple octopus named Otto waving from a coral reef, looking at the camera",
      "motion_prompt": "Slow zoom in on the octopus, gentle tentacle wave",
      "on_screen_text": null
    },
    {
      "id": "02",
      "duration_s": 6,
      "narration": "Twice a day, the sea rises... and twice a day, it falls. That's a tide.",
      "image_prompt": "Wide shot of a cartoon beach, water rising up the sand in a smooth wave",
      "motion_prompt": "Water level rises, camera holds steady",
      "on_screen_text": "TIDES"
    }
  ]
}
```

## Rules

- `meta.total_duration_s` MUST equal the sum of `scenes[].duration_s`. The renderer will reject mismatches.
- `meta.aspect_ratio` is one of `"9:16"` or `"16:9"`.
- `meta.style` is one of: `cartoon`, `whiteboard`, `anime`, `claymation`, `pixel-art`. Use `references/styles.md` to fill `style_suffix`.
- Each scene's `duration_s` should be between 3 and 12. Longer scenes get visually stale; shorter scenes don't give viewers time to read.
- `image_prompt` describes the still frame. The renderer appends `style_suffix` automatically.
- `motion_prompt` describes what should move when the still is animated. Keep it specific and physical ("camera dollies left", "subject tilts head") — vague prompts produce wobbly artifacts.
- `on_screen_text` is optional bold text overlay (separate from auto-generated captions from narration).
- `scenes[].id` is a two-digit string, sequential starting at `"01"`.

## Pacing guidance

| Total length | Typical scene count | Avg scene duration |
|---|---|---|
| 5-15s | 2-3 | 4-5s |
| 30s | 5-7 | 4-6s |
| 60s | 10-12 | 5-6s |
| 3 min | 30-36 | 5-6s |
| 10 min | 90-110 | 5-7s |
