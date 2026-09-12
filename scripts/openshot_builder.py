"""
OpenShot Project (.osp) Builder Script
Generates a fully compliant OpenShot 3.1.1 project file with all required libopenshot keyframe curves:
- time curve (advances video frames over timeline)
- gravity, scale, origin, transform curves
- audio and video timebases for smooth playback without black screens or freezes
"""

import argparse
import json
import os
import random
import string
import sys
from pathlib import Path


def generate_id(length=10):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def make_curve(y_val, interpolation=0):
    """Generates standard OpenShot Bezier curve point"""
    return {
        "Points": [
            {
                "co": {"X": 1.0, "Y": float(y_val)},
                "handle_left": {"X": 0.5, "Y": 1.0},
                "handle_right": {"X": 0.5, "Y": 0.0},
                "handle_type": 0,
                "interpolation": interpolation
            }
        ]
    }


def make_openshot_fade_curve(start_time, end_time, fade_in_sec=0.0, fade_out_sec=0.0, fps=30, peak_val=1.0):
    """
    Generates OpenShot Bezier curve points matching libopenshot coordinate space:
    Points are positioned at:
      start_of_clip = round(start_time * fps) + 1
      in_end = round((start_time + fade_in_sec) * fps) + 1
      out_start = round((end_time - fade_out_sec) * fps) + 1
      end_of_clip = round(end_time * fps) + 1
    """
    if fade_in_sec <= 0.0 and fade_out_sec <= 0.0:
        return make_curve(peak_val)

    fps_float = float(fps)
    start_of_clip = round(float(start_time) * fps_float) + 1
    end_of_clip = round(float(end_time) * fps_float) + 1

    points = []
    if fade_in_sec > 0.0:
        in_end = min(round((float(start_time) + fade_in_sec) * fps_float) + 1, end_of_clip)
        points.append({
            "co": {"X": float(start_of_clip), "Y": 0.0},
            "handle_left": {"X": 0.5, "Y": 1.0},
            "handle_right": {"X": 0.5, "Y": 0.0},
            "handle_type": 0,
            "interpolation": 0
        })
        points.append({
            "co": {"X": float(in_end), "Y": float(peak_val)},
            "handle_left": {"X": 0.5, "Y": 1.0},
            "handle_right": {"X": 0.5, "Y": 0.0},
            "handle_type": 0,
            "interpolation": 0
        })

    if fade_out_sec > 0.0:
        out_start = max(round((float(end_time) - fade_out_sec) * fps_float) + 1, start_of_clip)
        if not points:
            points.append({
                "co": {"X": float(start_of_clip), "Y": float(peak_val)},
                "handle_left": {"X": 0.5, "Y": 1.0},
                "handle_right": {"X": 0.5, "Y": 0.0},
                "handle_type": 0,
                "interpolation": 0
            })
        points.append({
            "co": {"X": float(out_start), "Y": float(peak_val)},
            "handle_left": {"X": 0.5, "Y": 1.0},
            "handle_right": {"X": 0.5, "Y": 0.0},
            "handle_type": 0,
            "interpolation": 0
        })
        points.append({
            "co": {"X": float(end_of_clip), "Y": 0.0},
            "handle_left": {"X": 0.5, "Y": 1.0},
            "handle_right": {"X": 0.5, "Y": 0.0},
            "handle_type": 0,
            "interpolation": 0
        })

    return {"Points": points}


def create_file_entry(filepath, file_id=None, media_type=None, duration=60.0, width=1280, height=720, fps_num=30, fps_den=1):
    if not file_id:
        file_id = generate_id()
    path_str = str(Path(filepath).resolve()).replace('\\', '/')

    suffix = Path(filepath).suffix.lower()
    if media_type is None:
        if suffix in IMAGE_EXTS:
            media_type = "image"
        elif suffix in {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg"}:
            media_type = "audio"
        else:
            media_type = "video"

    disp_num = 16 if width >= height else 9
    disp_den = 9 if width >= height else 16

    reader_type = "QtImageReader" if media_type == "image" else "FFmpegReader"
    has_image = media_type == "image"

    return {
        "id": file_id,
        "path": path_str,
        "media_type": media_type,
        "vcodec": "h264" if media_type == "video" else "",
        "acodec": "aac" if media_type in ["video", "audio"] else "",
        "width": width,
        "height": height,
        "fps": {"num": fps_num, "den": fps_den},
        "duration": float(duration),
        "video_length": int(duration * fps_num / fps_den),
        "file_size": os.path.getsize(filepath) if os.path.exists(filepath) else 1024,
        "has_video": media_type in ["video", "image"],
        "has_audio": media_type in ["video", "audio"],
        "has_single_image": has_image,
        "interlaced_frame": False,
        "top_field_first": True,
        "sample_rate": 48000,
        "channels": 2,
        "channel_layout": 3,
        "pixel_format": 0,
        "pixel_ratio": {"num": 1, "den": 1},
        "display_ratio": {"num": disp_num, "den": disp_den},
        "audio_stream_index": 1 if media_type in ["video", "audio"] else -1,
        "video_stream_index": 0 if media_type in ["video", "image"] else -1,
        "audio_timebase": {"num": 1, "den": 48000},
        "video_timebase": {"num": fps_den, "den": fps_num},
        "audio_bit_rate": 256000,
        "video_bit_rate": 8000000,
        "type": reader_type,
        "image": f"thumbnail/{file_id}.png"
    }


def create_clip_entry(file_entry, position, start, end, layer=1000000, fade_in=0.0, fade_out=0.0, volume=1.0, fps=30):
    clip_id = generate_id()

    alpha_curve = make_openshot_fade_curve(start_time=start, end_time=end, fade_in_sec=fade_in, fade_out_sec=fade_out, fps=fps, peak_val=1.0)
    vol_curve = make_openshot_fade_curve(start_time=start, end_time=end, fade_in_sec=fade_in, fade_out_sec=fade_out, fps=fps, peak_val=volume) if (fade_in > 0 or fade_out > 0) else make_curve(volume)

    return {
        "id": clip_id,
        "file_id": file_entry["id"],
        "title": Path(file_entry["path"]).name,
        "layer": layer,
        "position": float(position),
        "start": float(start),
        "end": float(end),
        "duration": float(file_entry["duration"]),
        # CRITICAL: time curve advances frames across timeline during playback
        "time": make_curve(1.0),
        "gravity": 4,      # Center gravity
        "scale": 1,        # 1 = Best Fit (prevents dark screens / cropping)
        "anchor": 0,
        "display": 0,
        "mixing": 0,
        "effects": [],
        "parentObjectId": "",
        "alpha": alpha_curve,
        "volume": vol_curve,
        "location_x": make_curve(0.0),
        "location_y": make_curve(0.0),
        "origin_x": make_curve(0.5),
        "origin_y": make_curve(0.5),
        "scale_x": make_curve(1.0),
        "scale_y": make_curve(1.0),
        "rotation": make_curve(0.0),
        "shear_x": make_curve(0.0),
        "shear_y": make_curve(0.0),
        "perspective_c1_x": make_curve(-1.0),
        "perspective_c1_y": make_curve(-1.0),
        "perspective_c2_x": make_curve(-1.0),
        "perspective_c2_y": make_curve(-1.0),
        "perspective_c3_x": make_curve(-1.0),
        "perspective_c3_y": make_curve(-1.0),
        "perspective_c4_x": make_curve(-1.0),
        "perspective_c4_y": make_curve(-1.0),
        "has_audio": make_curve(-1.0),   # -1.0 = Default / Auto Enabled
        "has_video": make_curve(-1.0),   # -1.0 = Default / Auto Enabled
        "channel_filter": make_curve(-1.0),
        "channel_mapping": make_curve(-1.0),
        "waveform": False,
        "wave_color": {
            "alpha": make_curve(255.0),
            "blue": make_curve(255.0),
            "green": make_curve(128.0),
            "red": make_curve(0.0)
        },
        "reader": dict(file_entry),
        "image": f"thumbnail/{file_entry['id']}.png"
    }



def create_openshot_project(manifest, output_osp_path):
    width = manifest.get("width", 1280)
    height = manifest.get("height", 720)
    fps = manifest.get("fps", 30)

    disp_num = 16 if width >= height else 9
    disp_den = 9 if width >= height else 16

    project = {
        "id": generate_id(),
        "fps": {"num": fps, "den": 1},
        "display_ratio": {"num": disp_num, "den": disp_den},
        "pixel_ratio": {"num": 1, "den": 1},
        "width": width,
        "height": height,
        "sample_rate": 48000,
        "channels": 2,
        "channel_layout": 3,
        "duration": 300.0,
        "scale": 135.0,
        "tick_pixels": 100,
        "playhead_position": 0,
        "profile": manifest.get("profile", f"HD {height}p {fps} fps" if width >= height else f"Vertical {width}x{height}"),
        "version": {
            "openshot-qt": "3.1.1",
            "libopenshot": "0.3.2"
        },
        "layers": [
            {"id": generate_id(), "number": 1000000, "y": 0, "label": "Main Visuals"},
            {"id": generate_id(), "number": 2000000, "y": 0, "label": "Voiceover"},
            {"id": generate_id(), "number": 3000000, "y": 0, "label": "BGM & Overlays"},
            {"id": generate_id(), "number": 4000000, "y": 0, "label": "Titles / Graphics"},
            {"id": generate_id(), "number": 5000000, "y": 0, "label": "Subtitles"}
        ],
        "files": [],
        "clips": [],
        "effects": [],
        "markers": [],
        "progress": [],
        "history": {"history": [], "current_index": 0},
        "settings": {}
    }

    files_cache = {}
    current_timeline_pos = 0.0

    raw_clips = manifest.get("clips", [])
    intro_fade_in = float(manifest.get("intro_fade_in", 0.0))
    outro_fade_out = float(manifest.get("outro_fade_out", 2.0))

    # Process visual clips
    for idx, item in enumerate(raw_clips):
        path = item["path"]
        dur = float(item.get("duration", 60.0))
        m_type = item.get("media_type")

        if path not in files_cache:
            file_entry = create_file_entry(
                path,
                media_type=m_type,
                duration=dur,
                width=width,
                height=height,
                fps_num=fps
            )
            files_cache[path] = file_entry
            project["files"].append(file_entry)
        else:
            file_entry = files_cache[path]

        start = float(item.get("start", 0.0))
        end = float(item.get("end", file_entry["duration"]))
        pos = float(item.get("position", current_timeline_pos))
        layer = int(item.get("layer", 1000000))

        # Pacing & Transitions:
        fade_in = float(item.get("fade_in", 0.0))
        fade_out = float(item.get("fade_out", 0.0))

        # After intro: smooth fade in as the video begins
        if idx == 0 and intro_fade_in > 0:
            fade_in = max(fade_in, intro_fade_in)

        # Smooth ending: slow fade out on final clip
        if idx == len(raw_clips) - 1 and outro_fade_out > 0:
            fade_out = max(fade_out, outro_fade_out)

        clip_entry = create_clip_entry(
            file_entry,
            position=pos,
            start=start,
            end=end,
            layer=layer,
            fade_in=fade_in,
            fade_out=fade_out,
            fps=fps
        )
        project["clips"].append(clip_entry)
        current_timeline_pos = max(current_timeline_pos, pos + (end - start))

    # Process Still Photos (if provided as separate list)
    for p_item in manifest.get("photos", []):
        p_path = p_item["path"]
        p_dur = float(p_item.get("duration", 4.0))
        if p_path not in files_cache:
            p_file = create_file_entry(
                p_path,
                media_type="image",
                duration=p_dur,
                width=width,
                height=height,
                fps_num=fps
            )
            files_cache[p_path] = p_file
            project["files"].append(p_file)
        else:
            p_file = files_cache[p_path]

        p_pos = float(p_item.get("position", current_timeline_pos))
        p_fade_in = float(p_item.get("fade_in", 0.8))
        p_fade_out = float(p_item.get("fade_out", 0.8))
        p_layer = int(p_item.get("layer", 1000000))

        p_clip = create_clip_entry(
            p_file,
            position=p_pos,
            start=0.0,
            end=p_dur,
            layer=p_layer,
            fade_in=p_fade_in,
            fade_out=p_fade_out,
            fps=fps
        )
        project["clips"].append(p_clip)
        current_timeline_pos = max(current_timeline_pos, p_pos + p_dur)

    # Process Voiceover
    if manifest.get("voiceover"):
        vo = manifest["voiceover"]
        vo_path = vo["path"]
        if vo_path not in files_cache:
            vo_file = create_file_entry(vo_path, media_type="audio", duration=vo.get("duration", current_timeline_pos))
            files_cache[vo_path] = vo_file
            project["files"].append(vo_file)
        else:
            vo_file = files_cache[vo_path]

        vo_clip = create_clip_entry(
            vo_file,
            position=vo.get("position", 0.0),
            start=vo.get("start", 0.0),
            end=vo.get("end", vo_file["duration"]),
            layer=2000000,
            fade_out=outro_fade_out if outro_fade_out > 0 else 0.0,
            fps=fps
        )
        project["clips"].append(vo_clip)

    # Process Background Music
    if manifest.get("bgm"):
        bgm = manifest["bgm"]
        bgm_path = bgm["path"]
        if bgm_path not in files_cache:
            bgm_file = create_file_entry(bgm_path, media_type="audio", duration=bgm.get("duration", current_timeline_pos))
            files_cache[bgm_path] = bgm_file
            project["files"].append(bgm_file)
        else:
            bgm_file = files_cache[bgm_path]

        bgm_clip = create_clip_entry(
            bgm_file,
            position=bgm.get("position", 0.0),
            start=bgm.get("start", 0.0),
            end=bgm.get("end", current_timeline_pos),
            layer=3000000,
            fade_in=float(bgm.get("fade_in", 2.0)),
            fade_out=max(float(bgm.get("fade_out", 2.0)), outro_fade_out),
            volume=float(bgm.get("volume", 0.25)),
            fps=fps
        )
        project["clips"].append(bgm_clip)

    # Process Audio Effects (SFX)
    for sfx_item in manifest.get("audio_effects", []) + manifest.get("sfx", []):
        sfx_path = sfx_item["path"]
        sfx_dur = float(sfx_item.get("duration", 3.0))
        if sfx_path not in files_cache:
            sfx_file = create_file_entry(sfx_path, media_type="audio", duration=sfx_dur)
            files_cache[sfx_path] = sfx_file
            project["files"].append(sfx_file)
        else:
            sfx_file = files_cache[sfx_path]

        sfx_clip = create_clip_entry(
            sfx_file,
            position=float(sfx_item.get("position", 0.0)),
            start=float(sfx_item.get("start", 0.0)),
            end=float(sfx_item.get("end", sfx_file["duration"])),
            layer=int(sfx_item.get("layer", 3000000)),
            fade_in=float(sfx_item.get("fade_in", 0.1)),
            fade_out=float(sfx_item.get("fade_out", 0.2)),
            volume=float(sfx_item.get("volume", 0.7)),
            fps=fps
        )
        project["clips"].append(sfx_clip)

    # Process Titles & Text Overlays (Layer 4000000)
    for title_item in manifest.get("titles", []) + manifest.get("text_overlays", []):
        t_path = title_item["path"]
        t_dur = float(title_item.get("duration", 4.0))
        if t_path not in files_cache:
            t_file = create_file_entry(t_path, media_type="image", duration=t_dur, width=width, height=height, fps_num=fps)
            files_cache[t_path] = t_file
            project["files"].append(t_file)
        else:
            t_file = files_cache[t_path]

        t_clip = create_clip_entry(
            t_file,
            position=float(title_item.get("position", 0.0)),
            start=0.0,
            end=t_dur,
            layer=int(title_item.get("layer", 4000000)),
            fade_in=float(title_item.get("fade_in", 0.5)),
            fade_out=float(title_item.get("fade_out", 0.5)),
            fps=fps
        )
        project["clips"].append(t_clip)

    # Process Subtitles (Layer 5000000)
    for sub_item in manifest.get("subtitles", []):
        sub_path = sub_item["path"]
        sub_dur = float(sub_item.get("duration", 3.0))
        if sub_path not in files_cache:
            sub_file = create_file_entry(sub_path, media_type="image", duration=sub_dur, width=width, height=height, fps_num=fps)
            files_cache[sub_path] = sub_file
            project["files"].append(sub_file)
        else:
            sub_file = files_cache[sub_path]

        sub_clip = create_clip_entry(
            sub_file,
            position=float(sub_item.get("position", 0.0)),
            start=0.0,
            end=sub_dur,
            layer=int(sub_item.get("layer", 5000000)),
            fade_in=float(sub_item.get("fade_in", 0.1)),
            fade_out=float(sub_item.get("fade_out", 0.1)),
            fps=fps
        )
        project["clips"].append(sub_clip)

    project["duration"] = max(current_timeline_pos, 30.0)

    out_path = Path(output_osp_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(project, f, indent=2)

    print(f"Successfully generated OpenShot project: {out_path}")
    print(f"Total clips: {len(project['clips'])}, Total assets: {len(project['files'])}, Timeline duration: {project['duration']:.2f}s")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Generate OpenShot .osp project")
    parser.add_argument("--manifest", required=True, help="Path to timeline manifest JSON")
    parser.add_argument("--output", required=True, help="Output .osp project file path")
    args = parser.parse_args()

    with open(args.manifest, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    create_openshot_project(manifest, args.output)


if __name__ == "__main__":
    main()
