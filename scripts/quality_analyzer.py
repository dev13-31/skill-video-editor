"""
Quality & Content Analyzer Script
Performs metadata scanning, blur detection (Laplacian variance), and static/repetitive frame detection.
"""

import argparse
import json
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

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff"}


def run_ffprobe_metadata(file_path):
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(file_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(res.stdout)
    except Exception as e:
        return None


def get_video_info(file_path):
    info = run_ffprobe_metadata(file_path)
    if not info:
        return {
            "path": str(file_path),
            "filename": Path(file_path).name,
            "duration": 0.0,
            "creation_time": None,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "error": "ffprobe_failed"
        }

    duration = float(info.get("format", {}).get("duration", 0.0))
    tags = info.get("format", {}).get("tags", {})
    creation_time = tags.get("creation_time")

    video_stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    width = int(video_stream.get("width", 1920))
    height = int(video_stream.get("height", 1080))
    
    fps_eval = 30.0
    r_frame_rate = video_stream.get("r_frame_rate", "30/1")
    if "/" in r_frame_rate:
        num, den = r_frame_rate.split("/")
        if float(den) > 0:
            fps_eval = float(num) / float(den)

    return {
        "path": str(file_path),
        "filename": Path(file_path).name,
        "duration": duration,
        "creation_time": creation_time,
        "width": width,
        "height": height,
        "fps": fps_eval
    }


def analyze_blur_and_static(video_path, blur_threshold=100.0, static_threshold=0.02, sample_interval=1.0):
    """
    Samples frames from video and calculates:
    - Laplacian variance for blur/focus detection
    - Normalized pixel difference for static/low-motion shot detection
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("[WARNING] opencv-python is not installed. Skipping deep visual blur/motion analysis.")
        return {"blur_score_mean": None, "static_ratio": 0.0, "low_motion_segments": []}

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {"error": "cannot_open_video"}

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_step = max(int(fps * sample_interval), 1)

    blur_scores = []
    diff_scores = []
    prev_gray = None
    low_motion_frames = 0
    sampled_count = 0

    frame_idx = 0
    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        blur_scores.append(float(lap_var))

        if prev_gray is not None:
            diff = cv2.absdiff(gray, prev_gray)
            norm_diff = np.mean(diff) / 255.0
            diff_scores.append(norm_diff)
            if norm_diff < static_threshold:
                low_motion_frames += 1

        prev_gray = gray
        sampled_count += 1
        frame_idx += frame_step
        if frame_idx >= total_frames:
            break

    cap.release()

    mean_blur = float(np.mean(blur_scores)) if blur_scores else 0.0
    static_ratio = (low_motion_frames / max(len(diff_scores), 1)) if diff_scores else 0.0

    return {
        "blur_score_mean": round(mean_blur, 2),
        "is_blurry": mean_blur < blur_threshold,
        "static_ratio": round(static_ratio, 3),
        "is_repetitive_static": static_ratio > 0.60
    }


def normalize_timestamp(ts_str):
    if not ts_str:
        return ""
    s = str(ts_str).strip()
    if len(s) >= 10 and s[4] == ":" and s[7] == ":":
        s = s[:4] + "-" + s[5:7] + "-" + s[8:]
    s = s.replace("T", " ")
    return s[:19]


def format_seconds(seconds):
    seconds = max(0.0, float(seconds))
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def get_image_info(file_path):
    creation_time = None
    width = 1920
    height = 1080
    try:
        from PIL import Image, ExifTags
        with Image.open(file_path) as img:
            width, height = img.size
            exif = img.getexif()
            if exif:
                for tag_id, value in exif.items():
                    tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                    if tag_name in ("DateTime", "DateTimeOriginal", "DateTimeDigitized"):
                        creation_time = str(value)
                        break
                if not creation_time and hasattr(exif, "get_ifd"):
                    try:
                        exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
                        for tag_id, value in exif_ifd.items():
                            tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                            if tag_name in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                                creation_time = str(value)
                                break
                    except Exception:
                        pass
    except Exception:
        pass

    if not creation_time:
        try:
            mtime = os.path.getmtime(file_path)
            from datetime import datetime
            creation_time = datetime.fromtimestamp(mtime).strftime("%Y:%m:%d %H:%M:%S")
        except Exception:
            pass

    return {
        "path": str(file_path),
        "filename": Path(file_path).name,
        "media_type": "image",
        "creation_time": creation_time,
        "normalized_timestamp": normalize_timestamp(creation_time),
        "width": width,
        "height": height,
        "duration": 4.0  # default on-screen display duration in seconds
    }


def scan_directory(assets_dir, min_duration=30.0, check_visuals=False, target_duration=None):
    assets_path = Path(assets_dir)
    video_files = [p for p in assets_path.iterdir() if p.suffix.lower() in VIDEO_EXTS]
    image_files = [p for p in assets_path.iterdir() if p.suffix.lower() in IMAGE_EXTS]

    results = []
    omitted = []
    total_raw_seconds = 0.0

    print(f"Scanning {len(video_files)} video clips and {len(image_files)} still photos in {assets_dir}...")
    for f in sorted(video_files):
        info = get_video_info(f)
        info["normalized_timestamp"] = normalize_timestamp(info.get("creation_time"))
        total_raw_seconds += info["duration"]
        if info["duration"] < min_duration:
            omitted.append({
                "filename": info["filename"],
                "duration": round(info["duration"], 2),
                "reason": f"Duration < {min_duration}s threshold"
            })
            continue

        if check_visuals:
            v_analysis = analyze_blur_and_static(f)
            info.update(v_analysis)

        results.append(info)

    # Sort video clips chronologically if timestamps exist, else by filename
    results.sort(key=lambda x: (x.get("normalized_timestamp") or "", x["filename"]))

    # Scan and sort still photos
    photos = []
    for img_path in sorted(image_files):
        img_info = get_image_info(img_path)
        photos.append(img_info)

    photos.sort(key=lambda x: (x.get("normalized_timestamp") or "", x["filename"]))

    # Map photo chronology with respect to video clips
    for photo in photos:
        p_ts = photo.get("normalized_timestamp") or ""
        if not p_ts or not results:
            photo["relative_position"] = "No timestamp comparison available"
            continue

        placed = False
        first_video_ts = results[0].get("normalized_timestamp") or ""
        if p_ts < first_video_ts:
            photo["relative_position"] = f"Before first video clip '{results[0]['filename']}'"
            placed = True

        if not placed:
            for i in range(len(results) - 1):
                cur_ts = results[i].get("normalized_timestamp") or ""
                next_ts = results[i + 1].get("normalized_timestamp") or ""
                if cur_ts <= p_ts <= next_ts:
                    photo["relative_position"] = f"Between '{results[i]['filename']}' and '{results[i+1]['filename']}'"
                    placed = True
                    break

        if not placed:
            photo["relative_position"] = f"After video clip '{results[-1]['filename']}'"

    # Compute total uncut video duration of retained clips
    total_uncut_seconds = sum(c["duration"] for c in results)

    # Build chronological sequence interleaving videos and photos
    combined_timeline = []
    for c in results:
        combined_timeline.append({
            "type": "video",
            "filename": c["filename"],
            "path": c["path"],
            "duration": round(c["duration"], 2),
            "timestamp": c.get("normalized_timestamp") or c.get("creation_time") or ""
        })
    for p in photos:
        combined_timeline.append({
            "type": "photo",
            "filename": p["filename"],
            "path": p["path"],
            "duration": round(p.get("duration", 4.0), 2),
            "timestamp": p.get("normalized_timestamp") or p.get("creation_time") or "",
            "relative_position": p.get("relative_position", "")
        })

    combined_timeline.sort(key=lambda x: (x.get("timestamp") or "", x["filename"]))

    # Target duration calculation
    target_analysis = {}
    if target_duration is not None and float(target_duration) > 0:
        tgt = float(target_duration)
        ratio = (total_uncut_seconds / tgt) if tgt > 0 and total_uncut_seconds > 0 else 1.0
        cuts_needed = max(0.0, total_uncut_seconds - tgt)
        rec_msg = (
            f"Trim {round(cuts_needed, 1)}s ({format_seconds(cuts_needed)}) across footage. Aim for an average cut retention of {round(100.0 / ratio, 1)}% per scene."
            if ratio > 1.0 else "Footage duration is already within target duration."
        )
        target_analysis = {
            "target_duration_seconds": round(tgt, 2),
            "target_duration_formatted": format_seconds(tgt),
            "cuts_needed_seconds": round(cuts_needed, 2),
            "cuts_needed_formatted": format_seconds(cuts_needed),
            "compression_ratio": round(ratio, 2),
            "recommendation": rec_msg
        }


    report = {
        "total_scanned_videos": len(video_files),
        "total_scanned_photos": len(image_files),
        "total_raw_video_duration_seconds": round(total_raw_seconds, 2),
        "total_raw_video_duration_formatted": format_seconds(total_raw_seconds),
        "total_uncut_video_duration_seconds": round(total_uncut_seconds, 2),
        "total_uncut_video_duration_formatted": format_seconds(total_uncut_seconds),
        "retained_clips": len(results),
        "omitted_clips": omitted,
        "clips": results,
        "still_photos": photos,
        "chronological_sequence": combined_timeline,
        "target_duration_analysis": target_analysis
    }
    return report


def main():
    parser = argparse.ArgumentParser(description="Analyze video and photo assets for quality, chronology, and timeline sorting")
    parser.add_argument("--scan-meta", help="Directory of video and photo assets to scan")
    parser.add_argument("--min-duration", type=float, default=30.0, help="Minimum duration in seconds for video clips")
    parser.add_argument("--target-duration", type=float, default=None, help="Desired target duration of final rendered video in seconds")
    parser.add_argument("--check-quality", action="store_true", help="Run Laplacian blur and static scene detection")
    parser.add_argument("--out", default="quality_report.json", help="Path to output JSON report")
    args = parser.parse_args()

    if not args.scan_meta:
        parser.print_help()
        sys.exit(1)

    report = scan_directory(
        args.scan_meta,
        min_duration=args.min_duration,
        check_visuals=args.check_quality,
        target_duration=args.target_duration
    )
    
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n=== Scanning & Quality Summary ===")
    print(f"Total video clips found: {report['total_scanned_videos']}")
    print(f"Total still photos found: {report['total_scanned_photos']}")
    print(f"Total Uncut Video Duration: {report['total_uncut_video_duration_formatted']} ({report['total_uncut_video_duration_seconds']}s)")
    print(f"Retained video clips: {report['retained_clips']}")
    print(f"Omitted clips (< {args.min_duration}s): {len(report['omitted_clips'])}")
    for o in report["omitted_clips"]:
        print(f"  - [OMITTED] {o['filename']} ({o['duration']}s): {o['reason']}")
    
    if report["still_photos"]:
        print(f"\nDiscovered {len(report['still_photos'])} still photos:")
        for p in report["still_photos"]:
            print(f"  - {p['filename']} (captured: {p['creation_time']}) -> {p.get('relative_position', 'chronological')}")

    if report.get("target_duration_analysis"):
        ta = report["target_duration_analysis"]
        print(f"\nTarget Duration: {ta['target_duration_formatted']} (compression: {ta['compression_ratio']}x)")
        print(f"Cuts Needed: {ta['cuts_needed_formatted']} ({ta['cuts_needed_seconds']}s)")
        print(f"Recommendation: {ta['recommendation']}")

    print(f"\nDetailed report written to: {args.out}")


if __name__ == "__main__":
    main()

