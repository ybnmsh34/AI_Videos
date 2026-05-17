#!/usr/bin/env python3
"""Render a storyboard.json into a finished MP4 — free stack only.

Usage:
    python3 render.py work/<slug>/storyboard.json

Pipeline per scene:
    1. Image (1 keyframe)  ←  pollinations.ai          (no auth)
    2. Motion clip          ←  ffmpeg zoompan (default)
                                 OR HuggingFace SVD if USE_HF_SVD=1
    3. Narration audio      ←  edge-tts                 (no auth)

Compose:
    - concat scene clips at FPS (default 24)
    - mix narration + optional music
    - burn captions
    - output to output/<slug>.mp4

Env vars (all optional):
    FPS=24                       output frame rate
    USE_HF_SVD=1                 try HuggingFace SVD for motion (free tier, may rate-limit)
    HF_TOKEN=hf_xxx              optional HF token (anonymous works for some models)
    OFFLINE_TTS=1                skip edge-tts, go straight to local Piper TTS
    MUSIC_FILE=/path/song.mp3    background music, ducked under narration
    MUSIC_VOLUME=0.18            music gain (0.0-1.0) before mix

The script is idempotent — existing scene assets are reused. Delete a scene's
files in scenes/ to force regeneration of that scene.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = REPO_ROOT / "output"

FPS = int(os.environ.get("FPS", "24"))
USE_HF_SVD = os.environ.get("USE_HF_SVD") == "1"
HF_TOKEN = os.environ.get("HF_TOKEN", "")
HF_SVD_MODEL = "stabilityai/stable-video-diffusion-img2vid-xt"


# ---------- helpers ----------

def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def log(msg: str) -> None:
    print(f"[render] {msg}", flush=True)


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if check and proc.returncode != 0:
        log(f"command failed: {' '.join(cmd)}")
        log(proc.stderr[-2000:])
        sys.exit(proc.returncode)
    return proc


def with_retry(fn, *, attempts: int = 3, base_delay: float = 2.0, label: str = "call"):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                raise
            delay = base_delay * (2 ** i)
            log(f"{label} failed ({type(e).__name__}: {e}); retrying in {delay:.0f}s")
            time.sleep(delay)


def aspect_to_dims(aspect: str) -> tuple[int, int]:
    if aspect == "9:16":
        return 1080, 1920
    if aspect == "16:9":
        return 1920, 1080
    die(f"unsupported aspect_ratio {aspect!r} (use '9:16' or '16:9')")
    return 0, 0  # unreachable


# ---------- image generation (pollinations.ai) ----------

def gen_image(ctx: "RenderContext", scene: dict, out_path: Path) -> None:
    if out_path.exists():
        log(f"  image cached: {out_path.name}")
        return

    style_suffix = ctx.storyboard["meta"].get("style_suffix", "")
    prompt = f"{scene['image_prompt']}, {style_suffix}".strip(", ")
    seed = int(scene["id"]) * 1000 + 7  # deterministic per scene
    params = {
        "width": str(ctx.width),
        "height": str(ctx.height),
        "seed": str(seed),
        "nologo": "true",
        "enhance": "true",
        "model": "flux",
    }
    url = (
        "https://image.pollinations.ai/prompt/"
        + urllib.parse.quote(prompt)
        + "?" + urllib.parse.urlencode(params)
    )

    def _download() -> None:
        req = urllib.request.Request(url, headers={"User-Agent": "ai-video-creator/1.0"})
        with urllib.request.urlopen(req, timeout=180) as r:
            data = r.read()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)

    log(f"  image (pollinations): {prompt[:90]}...")
    with_retry(_download, label="pollinations", base_delay=3.0)


# ---------- motion synthesis ----------

def gen_clip(ctx: "RenderContext", scene: dict, image_path: Path, out_path: Path) -> None:
    if out_path.exists():
        log(f"  clip cached: {out_path.name}")
        return

    if USE_HF_SVD:
        try:
            _gen_clip_hf_svd(ctx, scene, image_path, out_path)
            return
        except Exception as e:  # noqa: BLE001
            log(f"  HF SVD failed ({e}); falling back to ffmpeg motion")

    _gen_clip_ffmpeg(ctx, scene, image_path, out_path)


def _gen_clip_ffmpeg(ctx: "RenderContext", scene: dict, image_path: Path, out_path: Path) -> None:
    """Generate motion via ffmpeg zoompan / pan, choosing direction from motion_prompt."""
    duration = float(scene["duration_s"])
    frames = max(1, int(round(duration * FPS)))
    motion = (scene.get("motion_prompt") or "").lower()

    # Choose a motion preset
    if "zoom out" in motion or "pull back" in motion or "dolly out" in motion:
        z_expr = "if(eq(on,0),1.20,max(zoom-0.0008,1.0))"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif "pan left" in motion or "left" in motion:
        z_expr = "1.20"
        x_expr = "iw*0.20-(iw*0.20)*on/" + str(frames)
        y_expr = "ih/2-(ih/zoom/2)"
    elif "pan right" in motion or "right" in motion:
        z_expr = "1.20"
        x_expr = "(iw*0.20)*on/" + str(frames)
        y_expr = "ih/2-(ih/zoom/2)"
    elif "tilt up" in motion or "up" in motion:
        z_expr = "1.20"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih*0.20-(ih*0.20)*on/" + str(frames)
    elif "tilt down" in motion or "down" in motion:
        z_expr = "1.20"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "(ih*0.20)*on/" + str(frames)
    else:
        # default: slow Ken Burns zoom in
        z_expr = f"min(zoom+0.0009,1.25)"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"

    # Render at 2x output resolution intermediate to avoid zoompan jitter, then scale down
    inter_w = ctx.width * 2
    inter_h = ctx.height * 2

    vf = (
        f"scale={inter_w}:{inter_h}:force_original_aspect_ratio=increase,"
        f"crop={inter_w}:{inter_h},"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={frames}:s={ctx.width}x{ctx.height}:fps={FPS}"
    )

    log(f"  clip (ffmpeg-kenburns): {duration}s @ {FPS}fps  ({frames} frames)")
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-i", str(image_path),
        "-vf", vf,
        "-t", f"{duration}",
        "-r", str(FPS),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-an",
        str(out_path),
    ])


def _gen_clip_hf_svd(ctx: "RenderContext", scene: dict, image_path: Path, out_path: Path) -> None:
    """Generate motion via HuggingFace's free Stable Video Diffusion inference endpoint.

    SVD produces ~25 frames at 6fps natively (~4 seconds). We loop+interpolate to match
    the scene duration if necessary, then re-encode at FPS.
    """
    duration = float(scene["duration_s"])
    headers: dict[str, str] = {"Accept": "video/mp4"}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"

    url = f"https://api-inference.huggingface.co/models/{HF_SVD_MODEL}"
    image_bytes = image_path.read_bytes()
    raw_clip = out_path.with_suffix(".svd.mp4")

    def _call() -> None:
        req = urllib.request.Request(url, data=image_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=300) as r:
            raw_clip.write_bytes(r.read())

    log(f"  clip (HF-SVD): scene {scene['id']}, duration {duration}s")
    with_retry(_call, label="hf-svd", base_delay=5.0)

    # Re-time the ~4s SVD output to match scene duration (slow / loop / interpolate to FPS)
    probe = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(raw_clip),
    ])
    src_dur = float(probe.stdout.strip() or "4.0")
    pts_factor = max(0.25, min(4.0, duration / src_dur))

    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(raw_clip),
        "-vf", f"setpts={pts_factor}*PTS,minterpolate=fps={FPS}:mi_mode=mci,scale={ctx.width}:{ctx.height}",
        "-t", f"{duration}",
        "-r", str(FPS),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-an",
        str(out_path),
    ])
    raw_clip.unlink(missing_ok=True)


# ---------- TTS (edge-tts → piper offline fallback) ----------

OFFLINE_TTS = os.environ.get("OFFLINE_TTS") == "1"
PIPER_VOICES_DIR = Path(__file__).resolve().parent.parent / "voices"
PIPER_DEFAULT_VOICE = "en_US-amy-medium"  # matches Aria's warm-female vibe
PIPER_VOICE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# edge-tts voice → closest Piper voice
EDGE_TO_PIPER = {
    "en-US-AriaNeural": "en_US-amy-medium",
    "en-US-JennyNeural": "en_US-amy-medium",
    "en-US-GuyNeural": "en_US-ryan-medium",
    "en-US-DavisNeural": "en_US-ryan-medium",
    "en-US-AnaNeural": "en_US-amy-low",
    "en-US-TonyNeural": "en_US-ryan-medium",
    "en-GB-SoniaNeural": "en_GB-jenny_dioco-medium",
    "en-GB-RyanNeural": "en_GB-alan-medium",
    "en-AU-NatashaNeural": "en_GB-jenny_dioco-medium",
}


def gen_narration(ctx: "RenderContext", scene: dict, out_path: Path) -> None:
    if out_path.exists():
        log(f"  narration cached: {out_path.name}")
        return

    text = scene["narration"]
    voice_cfg = ctx.storyboard["meta"].get("voice", {})
    voice_id = voice_cfg.get("voice_id", "en-US-AriaNeural")

    if not OFFLINE_TTS:
        try:
            _tts_edge(text, voice_cfg, voice_id, out_path)
            return
        except Exception as e:  # noqa: BLE001
            log(f"  edge-tts failed ({e}); falling back to piper (offline)")

    _tts_piper(text, voice_id, out_path)


def _tts_edge(text: str, voice_cfg: dict, voice_id: str, out_path: Path) -> None:
    try:
        import edge_tts  # type: ignore
    except ImportError:
        raise RuntimeError("edge-tts not installed")

    rate = voice_cfg.get("rate", "+0%")
    pitch = voice_cfg.get("pitch", "+0Hz")
    volume = voice_cfg.get("volume", "+0%")

    async def _synth() -> None:
        communicate = edge_tts.Communicate(  # type: ignore
            text=text, voice=voice_id, rate=rate, pitch=pitch, volume=volume,
        )
        await communicate.save(str(out_path))

    log(f"  tts (edge-tts, {voice_id}): {text[:60]}...")
    with_retry(lambda: asyncio.run(_synth()), label="edge-tts", base_delay=3.0)


def _tts_piper(text: str, voice_id: str, out_path: Path) -> None:
    """Fully offline TTS via piper. Voice models are auto-downloaded once."""
    piper_voice = EDGE_TO_PIPER.get(voice_id, PIPER_DEFAULT_VOICE)
    onnx_path, json_path = _ensure_piper_voice(piper_voice)

    if not shutil.which("piper"):
        die(
            "piper TTS not installed. Run: bash .claude/skills/ai-video-creator/scripts/setup.sh\n"
            "(or: pip install --user piper-tts)"
        )

    wav_path = out_path.with_suffix(".wav")
    log(f"  tts (piper offline, {piper_voice}): {text[:60]}...")

    proc = subprocess.run(
        ["piper", "--model", str(onnx_path), "--output_file", str(wav_path)],
        input=text, text=True, capture_output=True, check=False,
    )
    if proc.returncode != 0:
        die(f"piper failed: {proc.stderr[-500:]}")

    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(wav_path),
        "-codec:a", "libmp3lame", "-b:a", "192k",
        str(out_path),
    ])
    wav_path.unlink(missing_ok=True)


def _ensure_piper_voice(voice_name: str) -> tuple[Path, Path]:
    """Download piper voice model on first use. Cached in voices/."""
    PIPER_VOICES_DIR.mkdir(parents=True, exist_ok=True)
    onnx_path = PIPER_VOICES_DIR / f"{voice_name}.onnx"
    json_path = PIPER_VOICES_DIR / f"{voice_name}.onnx.json"

    if onnx_path.exists() and json_path.exists():
        return onnx_path, json_path

    # Voice name format: lang_REGION-name-quality, e.g. en_US-amy-medium
    parts = voice_name.split("-")
    lang_region = parts[0]            # en_US
    lang = lang_region.split("_")[0]  # en
    speaker = parts[1]                # amy
    quality = parts[2] if len(parts) > 2 else "medium"

    base = f"{PIPER_VOICE_BASE}/{lang}/{lang_region}/{speaker}/{quality}"
    log(f"  downloading piper voice {voice_name} (one-time, ~50MB)...")

    for suffix, dest in ((".onnx", onnx_path), (".onnx.json", json_path)):
        url = f"{base}/{voice_name}{suffix}"
        req = urllib.request.Request(url, headers={"User-Agent": "ai-video-creator/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:
                shutil.copyfileobj(r, f)
        except Exception as e:  # noqa: BLE001
            die(f"failed to download piper voice {voice_name} ({suffix}): {e}\nURL: {url}")

    return onnx_path, json_path


# ---------- compose ----------

def compose(ctx: "RenderContext") -> Path:
    scenes = ctx.storyboard["scenes"]

    # 1. concat video-only scene clips (re-encoded so concat is reliable across codecs)
    concat_list = ctx.work_dir / "concat.txt"
    with open(concat_list, "w") as f:
        for s in scenes:
            clip = (ctx.scenes_dir / f"{s['id']}_clip.mp4").resolve()
            f.write(f"file '{clip}'\n")

    video_only = ctx.work_dir / "video_only.mp4"
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-vf", f"scale={ctx.width}:{ctx.height}:force_original_aspect_ratio=increase,crop={ctx.width}:{ctx.height},fps={FPS}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-an",
        str(video_only),
    ])

    # 2. Build per-scene narration with silence padding so it aligns with scene start times
    # Concat narrations end-to-end; pad each to scene duration with silence if shorter
    padded_narrations: list[Path] = []
    for s in scenes:
        src = ctx.scenes_dir / f"{s['id']}_narration.mp3"
        padded = ctx.scenes_dir / f"{s['id']}_narration_padded.wav"
        run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(src),
            "-af", f"apad=whole_dur={s['duration_s']},atrim=duration={s['duration_s']}",
            "-ar", "44100", "-ac", "2",
            str(padded),
        ])
        padded_narrations.append(padded)

    narr_concat = ctx.work_dir / "narration_concat.txt"
    with open(narr_concat, "w") as f:
        for p in padded_narrations:
            f.write(f"file '{p.resolve()}'\n")

    narration_full = ctx.work_dir / "narration_full.m4a"
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", str(narr_concat),
        "-c:a", "aac", "-b:a", "192k",
        str(narration_full),
    ])

    # 3. captions (Hormozi-style: bottom, white bold all-caps, green emphasis)
    ass_path = ctx.work_dir / "captions.ass"
    _write_ass(ctx, ass_path)

    # 4. music (optional)
    music_file = os.environ.get("MUSIC_FILE", "")
    music_volume = float(os.environ.get("MUSIC_VOLUME", "0.18"))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    final = OUTPUT_DIR / f"{ctx.slug}.mp4"

    vf = f"ass={ass_path.resolve()}"

    if music_file and Path(music_file).exists():
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(video_only),
            "-i", str(narration_full),
            "-stream_loop", "-1", "-i", str(music_file),
            "-filter_complex",
            f"[2:a]volume={music_volume}[bg];[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-vf", vf,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(final),
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(video_only),
            "-i", str(narration_full),
            "-map", "0:v", "-map", "1:a",
            "-vf", vf,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(final),
        ]
    run(cmd)
    return final


# Stopwords used to skip filler when picking the "emphasis" word in a caption chunk.
_CAPTION_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "of", "on", "in", "to", "for",
    "with", "at", "by", "is", "are", "was", "were", "be", "been", "being", "am",
    "do", "does", "did", "have", "has", "had", "i", "you", "he", "she", "it",
    "we", "they", "me", "him", "her", "us", "them", "my", "your", "his", "its",
    "our", "their", "this", "that", "these", "those", "what", "when", "where",
    "why", "how", "not", "no", "yes", "so", "than", "then", "as", "just", "like",
    "up", "down", "out", "over", "into", "from", "about",
}

# ASS colour format is &HAABBGGRR&
_CAPTION_WHITE = "&H00FFFFFF&"
_CAPTION_GREEN = "&H0000FF00&"   # bright pure green for the emphasis word


def _fmt_ass_time(t: float) -> str:
    h = int(t // 3600); t -= h * 3600
    m = int(t // 60); t -= m * 60
    s = int(t)
    cs = int(round((t - s) * 100))
    if cs == 100:
        s += 1; cs = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _pick_emphasis_idx(chunk: list[str]) -> int:
    """Choose which word in the chunk gets the green highlight.
    Prefer the longest non-stopword; fall back to the last word."""
    def clean(w: str) -> str:
        return re.sub(r"[^\w]", "", w).lower()

    candidates = [
        (i, w) for i, w in enumerate(chunk)
        if clean(w) and clean(w) not in _CAPTION_STOPWORDS
    ]
    if not candidates:
        return len(chunk) - 1
    return max(candidates, key=lambda iw: (len(clean(iw[1])), iw[0]))[0]


def _write_ass(ctx: "RenderContext", ass_path: Path) -> None:
    """Hormozi-style captions: short all-caps chunks at the bottom,
    white bold with thick black outline, one green emphasis word per chunk."""
    width = ctx.width
    height = ctx.height
    font_size = max(72, int(height * 0.058))   # ~111 at 1920px tall
    outline = max(5, int(font_size * 0.075))    # ~8
    margin_v = int(height * 0.14)               # sits in the lower third

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Anton,{font_size},{_CAPTION_WHITE},&H000000FF&,"
        f"&H00000000&,&H00000000&,1,0,0,0,100,100,0,0,1,{outline},0,2,"
        f"80,80,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )

    chunk_size = 4
    events: list[str] = []
    cursor = 0.0
    for scene in ctx.storyboard["scenes"]:
        duration = float(scene["duration_s"])
        words = scene["narration"].split()
        if not words:
            cursor += duration
            continue
        per_word = duration / len(words)
        chunks = [words[i : i + chunk_size] for i in range(0, len(words), chunk_size)]
        word_pos = 0
        for chunk in chunks:
            start = cursor + word_pos * per_word
            end = cursor + (word_pos + len(chunk)) * per_word
            emph = _pick_emphasis_idx(chunk)
            parts = []
            for i, w in enumerate(chunk):
                upper = w.upper()
                if i == emph:
                    parts.append(f"{{\\c{_CAPTION_GREEN}}}{upper}{{\\c{_CAPTION_WHITE}}}")
                else:
                    parts.append(upper)
            text = " ".join(parts)
            events.append(
                f"Dialogue: 0,{_fmt_ass_time(start)},{_fmt_ass_time(end)},"
                f"Default,,0,0,0,,{text}"
            )
            word_pos += len(chunk)
        cursor += duration

    ass_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


# ---------- entry ----------

@dataclass
class RenderContext:
    storyboard_path: Path
    storyboard: dict[str, Any]
    work_dir: Path
    scenes_dir: Path
    slug: str
    aspect_ratio: str
    width: int
    height: int


def validate(sb: dict[str, Any]) -> None:
    meta = sb.get("meta") or {}
    scenes = sb.get("scenes") or []
    if not scenes:
        die("storyboard has no scenes")
    if meta.get("aspect_ratio") not in ("9:16", "16:9"):
        die(f"meta.aspect_ratio must be '9:16' or '16:9', got {meta.get('aspect_ratio')!r}")
    total = float(meta.get("total_duration_s", 0))
    summed = sum(float(s["duration_s"]) for s in scenes)
    if abs(total - summed) > 0.1:
        die(f"meta.total_duration_s={total} ≠ sum of scene durations ({summed:.1f})")
    if total < 5 or total > 600:
        die(f"total duration {total}s out of supported range (5-600s)")
    for s in scenes:
        for k in ("id", "duration_s", "narration", "image_prompt"):
            if k not in s:
                die(f"scene {s.get('id', '?')} missing required field {k!r}")


def ffmpeg_check() -> None:
    if not shutil.which("ffmpeg"):
        die("ffmpeg not found in PATH. Install: apt-get install ffmpeg  /  brew install ffmpeg")
    if not shutil.which("ffprobe"):
        die("ffprobe not found in PATH (comes with ffmpeg).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("storyboard", type=Path)
    args = ap.parse_args()

    ffmpeg_check()

    sb_path: Path = args.storyboard
    if not sb_path.exists():
        die(f"storyboard not found: {sb_path}")

    storyboard = json.loads(sb_path.read_text())
    validate(storyboard)

    slug = storyboard["meta"]["slug"]
    work_dir = sb_path.parent
    scenes_dir = work_dir / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    aspect = storyboard["meta"]["aspect_ratio"]
    width, height = aspect_to_dims(aspect)

    ctx = RenderContext(
        storyboard_path=sb_path,
        storyboard=storyboard,
        work_dir=work_dir,
        scenes_dir=scenes_dir,
        slug=slug,
        aspect_ratio=aspect,
        width=width,
        height=height,
    )

    log(f"rendering '{slug}' — {len(storyboard['scenes'])} scenes, {storyboard['meta']['total_duration_s']}s total, {FPS}fps")
    if USE_HF_SVD:
        log("motion: HuggingFace SVD (with ffmpeg fallback)")
    else:
        log("motion: ffmpeg Ken Burns")

    for scene in storyboard["scenes"]:
        sid = scene["id"]
        log(f"scene {sid} ({scene['duration_s']}s):")
        img = scenes_dir / f"{sid}_image.png"
        clip = scenes_dir / f"{sid}_clip.mp4"
        narr = scenes_dir / f"{sid}_narration.mp3"
        gen_image(ctx, scene, img)
        gen_clip(ctx, scene, img, clip)
        gen_narration(ctx, scene, narr)

    log("compositing final MP4...")
    final = compose(ctx)
    log(f"DONE -> {final}")
    print(str(final))


if __name__ == "__main__":
    main()
