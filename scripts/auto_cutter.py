"""
Smart Speech & Silence Auto-Cutter Engine
Handles:
1. Speech vs dead-air silence detection (FFmpeg silencedetect)
2. Smart jump cut manifest generation (pruning awkward pauses while preserving natural speech margins)
3. Direct automated video assembly & rendering with click-free audio transitions
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

def ensure_ffmpeg_path():
    if not shutil.which("ffmpeg") and sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
                user_path = winreg.QueryValueEx(k, "Path")[0]
                os.environ["PATH"] = user_path + ";" + os.environ.get("PATH", "")
        except Exception:
            pass

ensure_ffmpeg_path()


def get_media_duration(file_path: str) -> float:
    """Returns duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())


def detect_silence_regions(
    media_path: str,
    silence_thresh_db: float = -30.0,
    min_silence_sec: float = 0.5
) -> List[Dict[str, float]]:
    """
    Detects silent pauses using FFmpeg silencedetect filter.
    Returns list of dicts: [{'start': 1.2, 'end': 2.5, 'duration': 1.3}, ...]
    """
    p = Path(media_path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Media file not found: {media_path}")

    cmd = [
        "ffmpeg",
        "-i", str(p),
        "-af", f"silencedetect=noise={silence_thresh_db}dB:d={min_silence_sec}",
        "-f", "null", "-"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    lines = res.stderr.split("\n")

    silences = []
    current_start = None
    for line in lines:
        if "silence_start:" in line:
            try:
                parts = line.split("silence_start:")
                current_start = float(parts[1].strip().split()[0])
            except Exception:
                pass
        elif "silence_end:" in line and current_start is not None:
            try:
                parts = line.split("silence_end:")
                end_val = float(parts[1].strip().split()[0])
                silences.append({
                    "start": round(current_start, 3),
                    "end": round(end_val, 3),
                    "duration": round(end_val - current_start, 3)
                })
                current_start = None
            except Exception:
                pass

    return silences


def compute_speech_keep_segments(
    total_duration: float,
    silence_regions: List[Dict[str, float]],
    pad_margin_sec: float = 0.12,
    min_speech_duration: float = 0.3
) -> List[Dict[str, float]]:
    """
    Inverts silence regions to find active speech intervals to keep.
    Adds a pad_margin before and after speech so audio words aren't abruptly clipped.
    Merges overlapping or adjacent intervals.
    """
    if not silence_regions:
        return [{"start": 0.0, "end": total_duration, "duration": total_duration}]

    # Invert silences to find raw speech intervals
    speech_intervals = []
    prev_end = 0.0

    for s in silence_regions:
        # Before this silence, there was speech (from prev_end to s['start'])
        if s["start"] > prev_end:
            speech_intervals.append({"start": prev_end, "end": s["start"]})
        prev_end = max(prev_end, s["end"])

    # Trailing speech after last silence
    if prev_end < total_duration:
        speech_intervals.append({"start": prev_end, "end": total_duration})

    # Apply padding margin and clamp within [0, total_duration]
    padded = []
    for seg in speech_intervals:
        st = max(0.0, seg["start"] - pad_margin_sec)
        en = min(total_duration, seg["end"] + pad_margin_sec)
        if (en - st) >= min_speech_duration:
            padded.append({"start": st, "end": en})

    if not padded:
        return [{"start": 0.0, "end": total_duration, "duration": total_duration}]

    # Merge overlapping intervals
    merged = []
    cur = padded[0]
    for nxt in padded[1:]:
        if nxt["start"] <= cur["end"]:
            cur["end"] = max(cur["end"], nxt["end"])
        else:
            merged.append({
                "start": round(cur["start"], 3),
                "end": round(cur["end"], 3),
                "duration": round(cur["end"] - cur["start"], 3)
            })
            cur = nxt

    merged.append({
        "start": round(cur["start"], 3),
        "end": round(cur["end"], 3),
        "duration": round(cur["end"] - cur["start"], 3)
    })

    return merged


def generate_auto_cut_manifest(
    media_path: str,
    output_json_path: Optional[str] = None,
    silence_thresh_db: float = -30.0,
    min_silence_sec: float = 0.5,
    pad_margin_sec: float = 0.12,
) -> Dict[str, Any]:
    """
    Calculates silence intervals and speech segments to keep, producing a structured cut manifest.
    """
    src = Path(media_path).resolve()
    duration = get_media_duration(str(src))
    silences = detect_silence_regions(str(src), silence_thresh_db=silence_thresh_db, min_silence_sec=min_silence_sec)
    keep_segments = compute_speech_keep_segments(duration, silences, pad_margin_sec=pad_margin_sec)

    total_cut_duration = sum(seg["duration"] for seg in keep_segments)
    time_saved = max(0.0, duration - total_cut_duration)
    compression_ratio = round(duration / total_cut_duration, 2) if total_cut_duration > 0 else 1.0
    retention_pct = round((total_cut_duration / duration) * 100, 1) if duration > 0 else 100.0

    manifest = {
        "source_file": str(src),
        "original_duration_seconds": round(duration, 2),
        "cut_duration_seconds": round(total_cut_duration, 2),
        "time_saved_seconds": round(time_saved, 2),
        "retention_percentage": retention_pct,
        "compression_ratio": compression_ratio,
        "silence_regions_count": len(silences),
        "keep_segments_count": len(keep_segments),
        "keep_segments": keep_segments,
        "silence_regions": silences
    }

    if output_json_path:
        out_p = Path(output_json_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        manifest["manifest_path"] = str(out_p)

    return manifest


def render_cut_video(
    input_video: str,
    output_video: str,
    keep_segments: List[Dict[str, float]],
    crf: int = 18,
    preset: str = "fast"
) -> str:
    """
    Renders the jump-cut video by stitching keep segments via FFmpeg filter_complex.
    """
    src = Path(input_video).resolve()
    out_p = Path(output_video).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    if not keep_segments:
        raise ValueError("keep_segments is empty; nothing to render.")

    # Build filtergraph
    filter_parts = []
    v_labels = []
    a_labels = []

    for i, seg in enumerate(keep_segments):
        st = seg["start"]
        en = seg["end"]
        filter_parts.append(
            f"[0:v]trim=start={st:.3f}:end={en:.3f},setpts=PTS-STARTPTS[v{i}];"
            f"[0:a]atrim=start={st:.3f}:end={en:.3f},asetpts=PTS-STARTPTS[a{i}]"
        )
        v_labels.append(f"[v{i}]")
        a_labels.append(f"[a{i}]")

    # Concat filter
    n = len(keep_segments)
    concat_inputs = "".join(f"{v_labels[i]}{a_labels[i]}" for i in range(n))
    concat_filter = f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]"
    full_filter = ";".join(filter_parts) + ";" + concat_filter

    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-filter_complex", full_filter,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-c:a", "aac",
        "-b:a", "256k",
        str(out_p)
    ]

    print(f"Rendering jump-cut video ({n} segments) to {out_p.name}...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg render failed:\n{res.stderr}")

    return str(out_p)


def auto_cut_video_pipeline(
    input_media: str,
    output_media: Optional[str] = None,
    silence_thresh_db: float = -30.0,
    min_silence_sec: float = 0.5,
    pad_margin_sec: float = 0.12,
    render: bool = True
) -> Dict[str, Any]:
    """
    End-to-end silence detection, manifest creation, and optional rendering.
    """
    src = Path(input_media).resolve()
    manifest_path = src.parent / f"{src.stem}_cut_manifest.json"
    manifest = generate_auto_cut_manifest(
        media_path=str(src),
        output_json_path=str(manifest_path),
        silence_thresh_db=silence_thresh_db,
        min_silence_sec=min_silence_sec,
        pad_margin_sec=pad_margin_sec
    )

    if render:
        out_v = output_media or str(src.parent / f"{src.stem}_jumpcut.mp4")
        rendered_file = render_cut_video(str(src), out_v, manifest["keep_segments"])
        manifest["rendered_video_path"] = rendered_file

    return manifest


def main():
    parser = argparse.ArgumentParser(description="Speech & Silence Auto-Cutter")
    parser.add_argument("media", help="Input video or audio path")
    parser.add_argument("--out", default=None, help="Output rendered video path")
    parser.add_argument("--thresh", type=float, default=-30.0, help="Silence dB threshold (default -30)")
    parser.add_argument("--min-silence", type=float, default=0.5, help="Minimum silence duration in seconds (default 0.5)")
    parser.add_argument("--pad", type=float, default=0.12, help="Padding margin in seconds around speech (default 0.12)")
    parser.add_argument("--no-render", action="store_true", help="Only compute cut manifest without rendering video")
    args = parser.parse_args()

    res = auto_cut_video_pipeline(
        input_media=args.media,
        output_media=args.out,
        silence_thresh_db=args.thresh,
        min_silence_sec=args.min_silence,
        pad_margin_sec=args.pad,
        render=not args.no_render
    )
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
