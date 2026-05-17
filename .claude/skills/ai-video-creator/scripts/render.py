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

def gen_image(ctx: "RenderContext", scene: dict, out_path: Path, variant_idx: int = 0) -> None:
    if out_path.exists():
        log(f"  image cached: {out_path.name}")
        return

    style_suffix = ctx.storyboard["meta"].get("style_suffix", "")
    prompt = f"{scene['image_prompt']}, {style_suffix}".strip(", ")
    # Deterministic seed per (scene, variant). variant_idx>0 spreads far enough
    # that Pollinations produces visibly different micro-poses but the long
    # character description in the prompt keeps the same identity.
    seed = int(scene["id"]) * 1000 + 7 + variant_idx * 131
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

    label = f"image v{variant_idx}" if variant_idx else "image"
    log(f"  {label} (pollinations): {prompt[:90]}...")
    with_retry(_download, label="pollinations", base_delay=3.0)


# ---------- motion synthesis ----------

# Camera-move presets used by the multi-image path. Each returns the
# (z, x, y) zoompan expressions for a given frame count. Rotating through
# these between variants keeps consecutive segments visually distinct.
_MOTION_PRESETS = {
    "zoom_in":   lambda f: ("min(zoom+0.0009,1.25)",
                            "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "zoom_out":  lambda f: ("if(eq(on,0),1.25,max(zoom-0.0008,1.05))",
                            "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "pan_right": lambda f: ("1.20",
                            f"(iw*0.20)*on/{f}", "ih/2-(ih/zoom/2)"),
    "pan_left":  lambda f: ("1.20",
                            f"iw*0.20-(iw*0.20)*on/{f}", "ih/2-(ih/zoom/2)"),
    "tilt_up":   lambda f: ("1.20",
                            "iw/2-(iw/zoom/2)", f"ih*0.20-(ih*0.20)*on/{f}"),
    "tilt_down": lambda f: ("1.20",
                            "iw/2-(iw/zoom/2)", f"(ih*0.20)*on/{f}"),
}
_MOTION_ROTATION = ["zoom_in", "pan_right", "zoom_out", "pan_left", "tilt_up", "tilt_down"]


def _n_variants_for(duration: float) -> int:
    """How many variant images / sub-clips to generate for a scene.
    Roughly one new image every ~5 seconds, clipped to a sane range."""
    return max(1, min(5, round(duration / 5)))


def _motion_for_scene(scene: dict, variant_idx: int) -> str:
    """Pick a motion preset for a given variant.
    Variant 0 honors the scene's motion_prompt; later variants rotate
    through the preset list so consecutive segments differ."""
    motion = (scene.get("motion_prompt") or "").lower()
    if variant_idx == 0:
        if "zoom out" in motion or "pull back" in motion or "dolly out" in motion:
            return "zoom_out"
        if "pan left" in motion or "left" in motion:
            return "pan_left"
        if "pan right" in motion or "right" in motion:
            return "pan_right"
        if "tilt up" in motion or " up" in f" {motion}":
            return "tilt_up"
        if "tilt down" in motion or " down" in f" {motion}":
            return "tilt_down"
        return "zoom_in"
    return _MOTION_ROTATION[variant_idx % len(_MOTION_ROTATION)]


def _probe_duration(p: Path) -> float:
    out = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(p),
    ])
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def gen_clip(ctx: "RenderContext", scene: dict, image_path: Path, out_path: Path) -> None:
    """Build a scene clip. For scenes long enough to warrant multiple images,
    generate N variants (same character prompt, different seeds, different
    camera moves) and crossfade them together. Otherwise single-image
    Ken Burns. Variant images and sub-clips are cached individually."""
    if out_path.exists():
        log(f"  clip cached: {out_path.name}")
        return

    duration = float(scene["duration_s"])
    n = _n_variants_for(duration)

    if n == 1:
        _gen_clip_segment(ctx, scene, image_path, out_path, duration,
                          motion=_motion_for_scene(scene, 0))
        return

    scenes_dir = image_path.parent
    sid = scene["id"]
    xfade = 0.4
    seg_dur = duration / n + xfade   # overlap absorbs the crossfade time

    sub_clips: list[Path] = []
    for i in range(n):
        variant_img = scenes_dir / f"{sid}_image_v{i:02d}.png"
        gen_image(ctx, scene, variant_img, variant_idx=i)
        sub_clip = scenes_dir / f"{sid}_clip_v{i:02d}.mp4"
        _gen_clip_segment(ctx, scene, variant_img, sub_clip, seg_dur,
                          motion=_motion_for_scene(scene, i))
        sub_clips.append(sub_clip)

    _xfade_chain(sub_clips, xfade_sec=xfade, target_duration=duration,
                 size=(ctx.width, ctx.height), out_path=out_path)


def _gen_clip_segment(ctx: "RenderContext", scene: dict, image_path: Path,
                      out_path: Path, duration: float, motion: str) -> None:
    """Single still → single Ken Burns clip with the named motion preset."""
    if out_path.exists():
        log(f"  sub-clip cached: {out_path.name}")
        return
    frames = max(1, int(round(duration * FPS)))
    z_expr, x_expr, y_expr = _MOTION_PRESETS[motion](frames)

    inter_w = ctx.width * 2
    inter_h = ctx.height * 2
    vf = (
        f"scale={inter_w}:{inter_h}:force_original_aspect_ratio=increase,"
        f"crop={inter_w}:{inter_h},"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':"
        f"d={frames}:s={ctx.width}x{ctx.height}:fps={FPS}"
    )
    log(f"  clip ({motion}): {duration:.2f}s @ {FPS}fps  ({frames} frames)")
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-i", str(image_path),
        "-vf", vf,
        "-t", f"{duration:.3f}",
        "-r", str(FPS),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-an",
        str(out_path),
    ])


def _xfade_chain(inputs: list[Path], xfade_sec: float, target_duration: float,
                 size: tuple[int, int], out_path: Path) -> None:
    """Crossfade a list of clips together via ffmpeg xfade, then trim/pad to
    target_duration. With N inputs there are N-1 crossfade transitions."""
    if len(inputs) == 1:
        shutil.copy(inputs[0], out_path)
        return

    durations = [_probe_duration(p) for p in inputs]
    parts: list[str] = []
    cum = durations[0]
    prev = "[0:v]"
    for i in range(1, len(inputs)):
        offset = max(0.0, cum - xfade_sec)
        label = f"[v{i:02d}]"
        parts.append(
            f"{prev}[{i}:v]xfade=transition=fade:duration={xfade_sec}"
            f":offset={offset:.3f}{label}"
        )
        cum += durations[i] - xfade_sec
        prev = label
    fc = ";".join(parts)

    cmd: list[str] = ["ffmpeg", "-y", "-loglevel", "error"]
    for inp in inputs:
        cmd += ["-i", str(inp)]
    cmd += [
        "-filter_complex", fc,
        "-map", prev,
        "-t", f"{target_duration:.3f}",
        "-r", str(FPS),
        "-s", f"{size[0]}x{size[1]}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-an",
        str(out_path),
    ]
    log(f"  xfade chain: {len(inputs)} sub-clips, {xfade_sec}s overlap -> {target_duration:.2f}s")
    run(cmd)


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

    # Stream so we can capture WordBoundary events (per-word timestamps)
    # alongside the audio. Sidecar JSON is consumed by the caption renderer.
    words_path = out_path.with_suffix(".words.json")

    async def _synth() -> None:
        communicate = edge_tts.Communicate(  # type: ignore
            text=text, voice=voice_id, rate=rate, pitch=pitch, volume=volume,
            boundary="WordBoundary",
        )
        words: list[dict] = []
        with open(out_path, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    # offset/duration are in 100-nanosecond ticks
                    words.append({
                        "text": chunk["text"],
                        "start": chunk["offset"] / 10_000_000.0,
                        "end": (chunk["offset"] + chunk["duration"]) / 10_000_000.0,
                    })
        words_path.write_text(json.dumps(words), encoding="utf-8")

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


# ASS colour format is &HAABBGGRR&
_CAPTION_WHITE = "&H00FFFFFF&"
_CAPTION_GREEN = "&H0000FF00&"


def _fmt_ass_time(t: float) -> str:
    h = int(t // 3600); t -= h * 3600
    m = int(t // 60); t -= m * 60
    s = int(t)
    cs = int(round((t - s) * 100))
    if cs == 100:
        s += 1; cs = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _load_word_timings(narration_path: Path, text: str, duration: float) -> list[dict]:
    """Return per-word [{text,start,end}] timings.
    Prefers the sidecar produced by edge-tts (real word boundaries);
    falls back to even-split when only Piper audio is available."""
    sidecar = narration_path.with_suffix(".words.json")
    if sidecar.exists():
        try:
            data = json.loads(sidecar.read_text())
            if data:
                return data
        except Exception:  # noqa: BLE001
            pass
    words = text.split()
    if not words:
        return []
    per = duration / len(words)
    return [
        {"text": w, "start": i * per, "end": (i + 1) * per}
        for i, w in enumerate(words)
    ]


def _chunk_words(timings: list[dict], max_words: int = 5) -> list[list[dict]]:
    """Group consecutive words into phrase-shaped cards: up to max_words,
    but break early at sentence/clause punctuation so phrases stay together."""
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    for w in timings:
        cur.append(w)
        last_char = w["text"][-1:] if w["text"] else ""
        ends_phrase = last_char in ".!?;:—"
        ends_clause = last_char == "," and len(cur) >= 3
        if len(cur) >= max_words or ends_phrase or ends_clause:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def _format_card(chunk: list[dict], active_idx: int, base_size: int, active_size: int) -> str:
    """Render a card's words with one active word styled green+larger.
    Cards of 4+ words wrap into 2 balanced lines (joined with \\N)."""
    parts: list[str] = []
    for j, w in enumerate(chunk):
        upper = w["text"].upper()
        if j == active_idx:
            parts.append(
                f"{{\\fs{active_size}\\c{_CAPTION_GREEN}}}{upper}"
                f"{{\\fs{base_size}\\c{_CAPTION_WHITE}}}"
            )
        else:
            parts.append(upper)
    if len(chunk) >= 4:
        mid = (len(chunk) + 1) // 2
        return " ".join(parts[:mid]) + r"\N" + " ".join(parts[mid:])
    return " ".join(parts)


def _write_ass(ctx: "RenderContext", ass_path: Path) -> None:
    """Karaoke captions in the Hormozi short-form style: lower-third,
    all-caps, white bold with a thick black outline, phrase-shaped cards
    that wrap into 2 lines when long. The word the narrator is currently
    speaking is bright green and ~35% larger; the highlight advances at
    each real word boundary captured from edge-tts."""
    width = ctx.width
    height = ctx.height
    base_size = max(72, int(height * 0.055))    # ~106 at 1920px tall
    active_size = int(base_size * 1.35)
    outline = max(5, int(base_size * 0.08))
    margin_v = int(height * 0.14)

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Anton,{base_size},{_CAPTION_WHITE},&H000000FF&,"
        f"&H00000000&,&H00000000&,1,0,0,0,100,100,0,0,1,{outline},0,2,"
        f"60,60,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )

    events: list[str] = []
    cursor = 0.0
    for idx, scene in enumerate(ctx.storyboard["scenes"], 1):
        duration = float(scene["duration_s"])
        narration_path = ctx.work_dir / "scenes" / f"{idx:02d}_narration.mp3"
        timings = _load_word_timings(narration_path, scene["narration"], duration)
        if not timings:
            cursor += duration
            continue

        for chunk in _chunk_words(timings, max_words=5):
            card_end = cursor + chunk[-1]["end"]
            # The active word "owns" the interval from its own start to the
            # next word's start (or the card end for the last word), so the
            # green highlight advances exactly with the speaker.
            for i, word in enumerate(chunk):
                slot_start = cursor + word["start"]
                slot_end = (cursor + chunk[i + 1]["start"]) if i + 1 < len(chunk) else card_end
                if slot_end <= slot_start:
                    continue
                events.append(
                    f"Dialogue: 0,{_fmt_ass_time(slot_start)},"
                    f"{_fmt_ass_time(slot_end)},Default,,0,0,0,,"
                    f"{_format_card(chunk, i, base_size, active_size)}"
                )
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
    log("motion: multi-image + crossfade (Pollinations stills, ffmpeg Ken Burns segments)")

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
