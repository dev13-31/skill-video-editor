"""
Visual Contact Sheet & Picture Board Generator
Features:
1. User-selectable Granularity (5s, 10s, 30s, 1m, 3m, 5m).
2. Major Hardcut / Scene Change Detection (extracts keyframes at camera/scene cuts).
3. Sequentially Numbered Thumbnails (#01, #02...) with timestamp and [HARD CUT] badges.
4. Filmstrip, Filmstrip + Waveform, and Multi-Clip Directory Picture Boards.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


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


def get_video_duration(video_path):
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return 0.0


def detect_hardcuts(video_path, threshold=0.35, max_cuts=60):
    """
    Detects major hardcuts / scene changes using FFmpeg scene detection filter.
    Returns list of timestamp floats in seconds.
    """
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", f"select='gt(scene,{threshold})',metadata=print:file=-",
        "-f", "null", "-",
        "-v", "quiet"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        lines = res.stdout.split("\n")
        pts_list = []
        for line in lines:
            if "pts_time:" in line:
                val = float(line.split("pts_time:")[1].strip())
                pts_list.append(val)
                if len(pts_list) >= max_cuts:
                    break
        return sorted(list(set([round(t, 2) for t in pts_list])))
    except Exception as e:
        print(f"[WARN] Hardcut detection skipped: {e}")
        return []


def extract_frame_at_timestamp(video_path, timestamp, output_jpg, width=360, height=202):
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{timestamp:.2f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        str(output_jpg)
    ]
    subprocess.run(cmd, capture_output=True)
    return os.path.exists(output_jpg) and os.path.getsize(output_jpg) > 0


def generate_waveform_image(video_path, output_png, width=1280, height=200):
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-filter_complex", f"aformat=channel_layouts=mono,showwavespic=s={width}x{height}:colors=#2ecc71",
        "-frames:v", "1",
        str(output_png)
    ]
    res = subprocess.run(cmd, capture_output=True)
    return os.path.exists(output_png)


def extract_granular_thumbnails(video_path, output_dir, interval=10, include_hardcuts=True):
    """
    Extracts thumbnails at regular time intervals AND at major hardcuts.
    Returns list of dicts: {"path": Path, "timestamp": float, "is_hardcut": bool}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    duration = get_video_duration(video_path)
    if duration <= 0:
        return []

    hardcuts = detect_hardcuts(video_path) if include_hardcuts else []

    timestamps = []
    # Add regular interval samples
    t = 0.0
    while t < duration:
        timestamps.append((t, False))
        t += interval

    # Add hardcuts if not within 1.5s of an existing interval sample
    for hc in hardcuts:
        if not any(abs(hc - existing_t) < 1.5 for existing_t, _ in timestamps):
            timestamps.append((hc, True))

    timestamps.sort(key=lambda x: x[0])

    extracted = []
    for idx, (ts, is_hc) in enumerate(timestamps, 1):
        thumb_path = output_dir / f"thumb_{idx:03d}_{ts:.1f}s.jpg"
        if not thumb_path.exists():
            extract_frame_at_timestamp(video_path, ts, thumb_path)
        if thumb_path.exists():
            extracted.append({
                "path": thumb_path,
                "timestamp": ts,
                "is_hardcut": is_hc,
                "index": idx
            })

    return extracted


def build_picture_board(items, output_image_path, title="VIDEO PICTURE BOARD", cols=5):
    """
    Renders a unified grid of numbered thumbnails with timestamps and hardcut badges.
    items: list of dicts with keys 'path', 'timestamp', 'is_hardcut', 'index', optional 'clip_name'
    """
    if not items:
        print("No items to assemble into picture board.")
        return None

    thumb_w = 360
    thumb_h = 202
    label_h = 44
    cell_w = thumb_w + 12
    cell_h = thumb_h + label_h + 12

    rows = (len(items) + cols - 1) // cols
    canvas_w = cols * cell_w + 24
    canvas_h = rows * cell_h + 84

    canvas = Image.new("RGB", (canvas_w, canvas_h), color=(20, 22, 26))
    draw = ImageDraw.Draw(canvas)

    # Header
    draw.text((25, 20), title.upper(), fill=(255, 215, 0))
    sub = f"Total Thumbnails: {len(items)} | Numbered sequentially for interactive review and omission"
    draw.text((25, 48), sub, fill=(170, 175, 185))

    for i, item in enumerate(items):
        r = i // cols
        c = i % cols
        x = 20 + c * cell_w
        y = 80 + r * cell_h

        is_hc = item.get("is_hardcut", False)
        border_col = (230, 126, 34) if is_hc else (60, 65, 75)
        border_width = 2 if is_hc else 1

        # Paste thumbnail
        try:
            im = Image.open(item["path"])
            canvas.paste(im, (x, y))
        except Exception:
            draw.rectangle([x, y, x + thumb_w, y + thumb_h], fill=(40, 40, 40))

        draw.rectangle([x, y, x + thumb_w, y + thumb_h], outline=border_col, width=border_width)

        # Label box underneath
        draw.rectangle([x, y + thumb_h, x + thumb_w, y + thumb_h + label_h], fill=(14, 16, 20))

        idx_tag = f"#{item.get('index', i+1):02d}"
        ts_sec = item.get("timestamp", 0.0)
        mins = int(ts_sec // 60)
        secs = int(ts_sec % 60)
        time_str = f"{mins:02d}:{secs:02d}"

        # Left label: Index & Time
        draw.text((x + 8, y + thumb_h + 6), f"{idx_tag}  [{time_str}]", fill=(245, 245, 245))

        clip_name = item.get("clip_name", "")
        if clip_name:
            draw.text((x + 8, y + thumb_h + 24), clip_name[:24], fill=(140, 150, 165))
        else:
            cut_label = "MAJOR HARD CUT" if is_hc else "SAMPLE"
            cut_color = (255, 165, 0) if is_hc else (120, 140, 160)
            draw.text((x + 8, y + thumb_h + 24), cut_label, fill=cut_color)

    canvas.save(output_image_path, quality=88)
    print(f"Picture Board saved to: {output_image_path}")
    return output_image_path


def main():
    parser = argparse.ArgumentParser(description="Generate visual contact sheets and picture boards")
    parser.add_argument("--mode", choices=["filmstrip", "waveform", "transcript", "picture_board"], default="picture_board")
    parser.add_argument("--input", required=True, help="Input video file or folder path")
    parser.add_argument("--out", default="picture_board.jpg", help="Output image file path")
    parser.add_argument("--interval", type=int, default=10, help="Interval in seconds between thumbnails")
    parser.add_argument("--hardcuts", action="store_true", help="Include major hardcuts / scene transitions")
    parser.add_argument("--cols", type=int, default=5, help="Grid columns")
    args = parser.parse_args()

    in_path = Path(args.input)
    temp_dir = Path("temp_thumbs")

    if in_path.is_file():
        items = extract_granular_thumbnails(in_path, temp_dir, interval=args.interval, include_hardcuts=args.hardcuts)
        build_picture_board(items, args.out, title=f"PICTURE BOARD: {in_path.stem}", cols=args.cols)
    else:
        print(f"Input is directory: {in_path}. Use directory mode.")


if __name__ == "__main__":
    main()
