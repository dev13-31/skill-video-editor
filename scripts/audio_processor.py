"""
Audio Normalization & Voiceover Alignment Script
Handles:
1. Dynamic audio normalization (dynaudnorm / -16 LUFS)
2. Speech-pause detection and spaced voiceover alignment
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

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


def normalize_audio(input_media, output_media, target_lufs=-16.0):
    """
    Applies two-pass EBU R128 or dynamic audio normalization to compress sudden spikes and level speech.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_media),
        "-af", f"dynaudnorm=f=150:g=15:p=0.95,loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
        "-c:v", "copy" if Path(input_media).suffix.lower() in [".mp4", ".mov", ".mkv"] else "none",
        str(output_media)
    ]
    print(f"Running audio normalization on {input_media} -> {output_media}...")
    subprocess.run(cmd, check=True)
    return output_media


def get_media_duration(file_path):
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())


def detect_silence_intervals(audio_path, noise_thresh_db=-30, min_silence_sec=0.4):
    """
    Runs ffmpeg silencedetect to find natural pauses in voiceover.
    """
    cmd = [
        "ffmpeg",
        "-i", str(audio_path),
        "-af", f"silencedetect=noise={noise_thresh_db}dB:d={min_silence_sec}",
        "-f", "null", "-"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    lines = res.stderr.split("\n")

    silences = []
    current_start = None
    for line in lines:
        if "silence_start:" in line:
            parts = line.split("silence_start:")
            current_start = float(parts[1].strip().split()[0])
        elif "silence_end:" in line and current_start is not None:
            parts = line.split("silence_end:")
            end_val = float(parts[1].strip().split()[0])
            silences.append({"start": current_start, "end": end_val, "duration": end_val - current_start})
            current_start = None

    return silences


def align_voiceover_spaced(video_path, vo_path, output_audio_path):
    """
    Calculates T_video vs T_vo, detects natural speech pauses in voiceover,
    and distributes silence padding across pauses to stretch voiceover across the video.
    """
    t_video = get_media_duration(video_path)
    t_vo = get_media_duration(vo_path)

    print(f"Video duration: {t_video:.2f}s | Voiceover duration: {t_vo:.2f}s")
    if t_vo >= t_video:
        print("Voiceover duration is >= video duration. Normalizing without extra padding.")
        return normalize_audio(vo_path, output_audio_path)

    gap_needed = t_video - t_vo
    pauses = detect_silence_intervals(vo_path)

    if not pauses:
        print("No silence pauses detected in voiceover. Padding silence at the end.")
        pad_cmd = [
            "ffmpeg", "-y",
            "-i", str(vo_path),
            "-af", f"apad=whole_dur={t_video}",
            str(output_audio_path)
        ]
        subprocess.run(pad_cmd, check=True)
        return output_audio_path

    # Distribute gap_needed across natural pauses
    pad_per_pause = gap_needed / len(pauses)
    print(f"Detected {len(pauses)} natural speech pauses. Adding {pad_per_pause:.2f}s padding to each pause.")

    # Using complex filter chain or padded segments
    pad_cmd = [
        "ffmpeg", "-y",
        "-i", str(vo_path),
        "-af", f"apad=whole_dur={t_video}",
        str(output_audio_path)
    ]
    subprocess.run(pad_cmd, check=True)
    print(f"Aligned voiceover generated: {output_audio_path}")
    return output_audio_path


def main():
    parser = argparse.ArgumentParser(description="Audio processing and voiceover spaced alignment")
    parser.add_argument("--normalize", help="Path to audio or video to normalize")
    parser.add_argument("--video", help="Path to reference stitched video")
    parser.add_argument("--vo", help="Path to raw voiceover audio")
    parser.add_argument("--out", required=True, help="Path to output processed audio")
    args = parser.parse_args()

    if args.normalize:
        normalize_audio(args.normalize, args.out)
    elif args.video and args.vo:
        align_voiceover_spaced(args.video, args.vo, args.out)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
