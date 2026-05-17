# AI_Videos

A CapCut-style AI video generator delivered as a **Claude Code skill**. Activate the skill in any Claude Code session and ask Claude to make a video — Claude writes the script, builds the storyboard, and drives a free-stack rendering pipeline that produces a finished 24fps MP4.

## What it does

Turns a prompt like *"a 30-second cartoon about why the ocean has tides"* into a finished animated short with:

- AI-generated cartoon visuals (1 keyframe per scene)
- Smooth motion synthesized at 24fps via FFmpeg (or HuggingFace SVD if enabled)
- AI voiceover narration (Microsoft Edge neural voices via edge-tts)
- Burned-in TikTok-style captions
- Optional background music
- Vertical 9:16 (default) or horizontal 16:9 output
- Length 5 seconds to 10 minutes

## Free-stack — no paid API keys required

| Capability | Free tool |
|---|---|
| Image generation | [pollinations.ai](https://pollinations.ai) (zero-auth) |
| Image-to-video (optional) | [HuggingFace SVD](https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt) free inference |
| Motion synthesis (default) | FFmpeg `zoompan` / Ken Burns / parallax |
| TTS narration | [edge-tts](https://github.com/rany2/edge-tts) (Microsoft Edge neural voices) |
| Music (optional) | Pixabay royalty-free, or bring your own |
| Composition | FFmpeg |

## Setup

```bash
# one-time
bash .claude/skills/ai-video-creator/scripts/setup.sh
```

Requires Python 3.10+ and `ffmpeg`. The setup script installs `ffmpeg` (if missing) and `edge-tts`.

## Usage

Open this repo in Claude Code, then just ask:

> "Make a 30-second cartoon explaining why the ocean has tides."

Claude detects the request, invokes the `ai-video-creator` skill, asks any clarifying questions, writes the script and storyboard, and runs the renderer. The final MP4 lands at `output/<slug>.mp4`.

## Architecture

```
.claude/skills/ai-video-creator/
├── SKILL.md                          # Instructions for Claude
├── prompts/
│   ├── script-system.md              # Narration voice/tone rules
│   └── scene-prompt-tips.md          # Image/motion prompt patterns
├── references/
│   ├── storyboard-schema.md          # JSON schema spec
│   ├── styles.md                     # Visual style presets
│   ├── voice-presets.md              # edge-tts voice IDs
│   └── example-storyboard.json       # Reference storyboard
└── scripts/
    ├── render.py                     # The pipeline (image → motion → tts → compose)
    ├── setup.sh                      # One-time dep install
    └── requirements.txt              # Python deps

work/<slug>/                          # Per-video working dir (gitignored)
  script.md
  storyboard.json
  scenes/
    01_image.png  01_clip.mp4  01_narration.mp3
    ...

output/<slug>.mp4                     # Final deliverable (gitignored)
```

## Optional upgrades

Set before running:

| Env var | Effect |
|---|---|
| `USE_HF_SVD=1` | Use HuggingFace Stable Video Diffusion for image-to-video instead of FFmpeg motion. Higher quality, may rate-limit. Falls back automatically. |
| `HF_TOKEN=hf_xxx` | Lifts anonymous HF rate limits if you have a token. |
| `MUSIC_FILE=/path/to/song.mp3` | Adds background music, ducked under narration. |
| `MUSIC_VOLUME=0.18` | Music gain before mix (0.0 to 1.0). |
| `FPS=30` | Override 24fps default. |

## Manual rendering

Skip Claude and render a hand-written storyboard:

```bash
python3 .claude/skills/ai-video-creator/scripts/render.py work/my-video/storyboard.json
```

See `.claude/skills/ai-video-creator/references/example-storyboard.json` for the exact format.
