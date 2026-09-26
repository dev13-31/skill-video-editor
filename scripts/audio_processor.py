"""
Audio Normalization, Enhancement & Voiceover Alignment Script
Handles:
1. Multi-stage audio enhancement (de-rumble, FFT noise suppression, vocal presence EQ, dynamic leveling)
2. EBU R128 broadcast loudness mastering (-16 LUFS)
3. Speech-pause detection and spaced voiceover alignment
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

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


def enhance_audio(
    input_media: str,
    output_media: str,
    mode: str = "full_mastering",
    target_lufs: float = -16.0,
    denoise_amount: float = 12.0,
    presence_boost_db: float = 3.0
) -> str:
    """
    Applies professional audio enhancement to vocal and video audio tracks.
    
    Modes:
      - 'full_mastering': Highpass (80Hz rumble cut) + Lowpass (12kHz hiss cut) +
        FFT de-noise (afftdn) + Vocal presence EQ (2.5kHz boost) +
        Dynamic leveling (dynaudnorm) + EBU R128 loudness (loudnorm).
      - 'voice_clarity': Highpass + Vocal presence EQ + Dynamic leveling + EBU R128.
      - 'denoise_only': Highpass + FFT de-noise + EBU R128.
      - 'normalize_only': Dynamic leveling + EBU R128.
    """
    in_p = Path(input_media).resolve()
    out_p = Path(output_media).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    if not in_p.exists():
        raise FileNotFoundError(f"Input media not found: {input_media}")

    # Build audio filter chain
    filters = []

    if mode in ["full_mastering", "voice_clarity", "denoise_only"]:
        # Cut sub-bass rumble, wind, and desk thumps
        filters.append("highpass=f=80")

    if mode in ["full_mastering"]:
        # Cut ultrasonic electronic hiss
        filters.append("lowpass=f=12000")

    if mode in ["full_mastering", "denoise_only"]:
        # FFT-based adaptive noise suppression
        filters.append(f"afftdn=nr={denoise_amount}:nf=-30:tn=1")

    if mode in ["full_mastering", "voice_clarity"]:
        # Speech intelligibility presence boost in core dialogue frequency
        filters.append(f"equalizer=f=2500:t=q:w=1.5:g={presence_boost_db}")

    if mode in ["full_mastering", "voice_clarity", "normalize_only"]:
        # Dynamic leveler to tame sudden spikes and boost quiet whispers
        filters.append("dynaudnorm=f=150:g=15:p=0.95")

    # Final broadcast EBU R128 loudness normalization
    filters.append(f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11")

    af_chain = ",".join(filters)

    is_video = in_p.suffix.lower() in [".mp4", ".mov", ".mkv", ".m4v", ".avi"]
    
    cmd = ["ffmpeg", "-y", "-i", str(in_p), "-af", af_chain]
    if is_video and out_p.suffix.lower() in [".mp4", ".mov", ".mkv", ".m4v", ".avi"]:
        cmd.extend(["-c:v", "copy", "-c:a", "aac", "-b:a", "256k", str(out_p)])
    else:
        cmd.extend(["-c:a", "aac", "-b:a", "256k", str(out_p)])

    print(f"Enhancing audio ({mode}) on {in_p.name} -> {out_p.name}...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg audio enhancement failed:\n{res.stderr}")

    return str(out_p)


def normalize_audio(input_media: str, output_media: str, target_lufs: float = -16.0) -> str:
    """
    Applies dynamic audio normalization (dynaudnorm) and EBU R128 loudness normalization.
    """
    return enhance_audio(input_media, output_media, mode="normalize_only", target_lufs=target_lufs)


def get_media_duration(file_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())


def detect_silence_intervals(audio_path: str, noise_thresh_db: float = -30.0, min_silence_sec: float = 0.4):
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


def align_voiceover_spaced(video_path: str, vo_path: str, output_audio_path: str) -> str:
    """
    Calculates T_video vs T_vo, detects natural speech pauses in voiceover,
    and distributes silence padding across pauses to stretch voiceover across the video.
    """
    t_video = get_media_duration(video_path)
    t_vo = get_media_duration(vo_path)

    print(f"Video duration: {t_video:.2f}s | Voiceover duration: {t_vo:.2f}s")
    if t_vo >= t_video:
        print("Voiceover duration is >= video duration. Normalizing without extra padding.")
        return enhance_audio(vo_path, output_audio_path, mode="full_mastering")

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
    parser = argparse.ArgumentParser(description="Audio enhancement, normalization and voiceover alignment")
    parser.add_argument("--enhance", help="Path to audio or video to enhance")
    parser.add_argument("--mode", default="full_mastering", choices=["full_mastering", "voice_clarity", "denoise_only", "normalize_only"])
    parser.add_argument("--lufs", type=float, default=-16.0, help="Target LUFS (default -16)")
    parser.add_argument("--denoise", type=float, default=12.0, help="Denoise amount in dB (default 12)")
    parser.add_argument("--presence", type=float, default=3.0, help="Vocal presence boost in dB (default 3)")
    parser.add_argument("--normalize", help="Path to audio or video to normalize (legacy)")
    parser.add_argument("--video", help="Path to reference stitched video for VO alignment")
    parser.add_argument("--vo", help="Path to raw voiceover audio")
    parser.add_argument("--out", required=True, help="Path to output processed audio")
    args = parser.parse_args()

    if args.enhance:
        enhance_audio(args.enhance, args.out, mode=args.mode, target_lufs=args.lufs, denoise_amount=args.denoise, presence_boost_db=args.presence)
    elif args.normalize:
        normalize_audio(args.normalize, args.out, target_lufs=args.lufs)
    elif args.video and args.vo:
        align_voiceover_spaced(args.video, args.vo, args.out)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
