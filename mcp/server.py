"""
Video Editor Custom MCP Server
Exposes automated video editing tools:
- Scanning & metadata filtering
- Visual contact sheet generation
- Blur & motion quality scoring
- Multilingual Speech-to-Text (STT) & word timestamps (faster-whisper)
- Synchronized animated subtitles (.ass karaoke & active-word highlight)
- Subtitle burning into video (FFmpeg libass)
- Speech & silence auto-cutting (jump-cut creation)
- Multi-stage audio enhancement (de-rumble, FFT noise suppression, vocal EQ, EBU R128 loudness)
- OpenShot .osp project compilation
- Export rendering
"""

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

from mcp.server.mcpserver import MCPServer

# Add sibling scripts to path
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

try:
    import contact_sheet
    import quality_analyzer
    import audio_processor
    import openshot_builder
    import speech_transcriber
    import auto_cutter
except ImportError:
    pass

server = MCPServer(
    name="video-editor",
    instructions="Video editing assistant tools for scanning footage, analyzing quality, multilingual speech transcription (STT), synchronized animated subtitles, silence/speech cutting, audio enhancement/normalization, and rendering exports."
)


@server.tool()
def video_scan_assets(folder_path: str, min_duration: float = 30.0, check_visuals: bool = False, target_duration: float = 0.0) -> str:
    """
    Scans a directory of video clips and still photos.
    Extracts metadata, prunes clips shorter than min_duration, sorts chronologically,
    calculates total uncut runtime, maps still photos chronology wrt video timing,
    and computes cutting requirements if target_duration is provided.
    """
    if not os.path.exists(folder_path):
        return json.dumps({"error": f"Path '{folder_path}' does not exist."})
    
    tgt = target_duration if target_duration > 0 else None
    report = quality_analyzer.scan_directory(folder_path, min_duration=min_duration, check_visuals=check_visuals, target_duration=tgt)
    return json.dumps(report, indent=2)


@server.tool()
def video_extract_frame(
    video_path: str,
    timestamp: float,
    output_path: str = "",
    width: int = 1920,
    height: int = 1080
) -> str:
    """
    Extracts a single high-resolution video frame at the specified timestamp (in seconds)
    for YouTube thumbnail generation or preview.
    """
    if not os.path.exists(video_path):
        return json.dumps({"error": f"Video '{video_path}' not found."})

    if not output_path:
        stem = Path(video_path).stem
        output_path = str(Path(video_path).parent / f"{stem}_frame_{int(timestamp)}s.png")

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{timestamp:.2f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        str(out_p)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return json.dumps({"status": "success", "extracted_frame_path": str(out_p)})
    except subprocess.CalledProcessError as e:
        return json.dumps({"error": "Frame extraction failed", "details": e.stderr.decode() if e.stderr else str(e)})


@server.tool()
def video_generate_contact_sheet(
    video_path: str,
    output_path: str = "",
    mode: str = "filmstrip",
    interval: int = 10,
    cols: int = 4
) -> str:
    """
    Generates a visual contact sheet / storyboard preview.
    Modes:
      - 'filmstrip': Grid of thumbnails sampled every 'interval' seconds.
      - 'waveform': Thumbnails grid combined with audio amplitude waveform.
    """
    if not os.path.exists(video_path):
        return json.dumps({"error": f"Video '{video_path}' not found."})

    if not output_path:
        stem = Path(video_path).stem
        output_path = str(Path(video_path).parent / f"{stem}_contact_sheet.jpg")

    temp_dir = Path(video_path).parent / "temp_thumbs"
    thumbs = contact_sheet.extract_thumbnails(video_path, temp_dir, interval=interval)

    if not thumbs:
        return json.dumps({"error": "Failed to extract thumbnails from video."})

    if mode == "waveform":
        wave_png = str(Path(video_path).parent / "temp_wave.png")
        contact_sheet.generate_waveform_image(video_path, wave_png)
        res = contact_sheet.build_filmstrip_with_waveform(thumbs, wave_png, output_path, cols=cols)
        if os.path.exists(wave_png):
            os.remove(wave_png)
    else:
        res = contact_sheet.build_filmstrip_image(thumbs, output_path, cols=cols)

    # Cleanup temp thumbs
    for t in thumbs:
        try:
            t.unlink()
        except:
            pass
    if temp_dir.exists():
        try:
            temp_dir.rmdir()
        except:
            pass

    return json.dumps({"status": "success", "contact_sheet_path": str(res)})


@server.tool()
def video_analyze_quality(
    video_path: str,
    blur_threshold: float = 100.0,
    static_threshold: float = 0.02
) -> str:
    """
    Analyzes video frame clarity and motion.
    Computes Laplacian focus variance (flags blurry clips) and optical flow/frame differences (flags static scenes).
    """
    if not os.path.exists(video_path):
        return json.dumps({"error": f"Video '{video_path}' not found."})

    res = quality_analyzer.analyze_blur_and_static(video_path, blur_threshold=blur_threshold, static_threshold=static_threshold)
    return json.dumps(res, indent=2)


@server.tool()
def video_transcribe_audio(
    media_path: str,
    model_size: str = "base",
    language: str = "",
    task: str = "transcribe",
    aspect_ratio: str = "16:9",
    style_mode: str = "highlight",
    words_per_card: int = 4,
    highlight_color_hex: str = "#FFD700"
) -> str:
    """
    Transcribes audio or video speech using faster-whisper with word-level timestamps.
    Supports multilingual recognition (English, Hindi, Spanish, etc.), auto language detection,
    and exports JSON, SRT, VTT, and synchronized animated ASS subtitles.
    """
    if not os.path.exists(media_path):
        return json.dumps({"error": f"Media '{media_path}' not found."})

    lang = language.strip() if language.strip() else None

    try:
        res = speech_transcriber.run_full_stt_pipeline(
            media_path=media_path,
            model_size=model_size,
            language=lang,
            aspect_ratio=aspect_ratio,
            style_mode=style_mode,
            words_per_card=words_per_card,
            highlight_color_hex=highlight_color_hex
        )
        return json.dumps(res, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"STT transcription failed: {str(e)}"})


@server.tool()
def video_generate_animated_subtitles(
    transcript_json_path: str,
    output_ass_path: str = "",
    style_mode: str = "highlight",
    aspect_ratio: str = "16:9",
    words_per_card: int = 4,
    primary_color_hex: str = "#FFFFFF",
    highlight_color_hex: str = "#FFD700",
    font_name: str = "",
    font_size: int = 0
) -> str:
    r"""
    Generates synchronized animated ASS subtitles from an existing transcript JSON.
    Modes:
      - 'highlight': Spoken words dynamically pop into highlight_color (e.g. Bright Gold).
      - 'karaoke': Smooth left-to-right sweep color fill (\\kf tags).
      - 'clean': Punchy synchronized cards.
    """
    if not os.path.exists(transcript_json_path):
        return json.dumps({"error": f"Transcript JSON '{transcript_json_path}' not found."})

    try:
        with open(transcript_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        words = data.get("words", [])
        if not words:
            return json.dumps({"error": "No word timestamps found in transcript JSON."})

        lang = data.get("detected_language", "en")
        
        if not output_ass_path:
            p = Path(transcript_json_path)
            output_ass_path = str(p.parent / f"{p.stem.replace('_transcript', '')}_animated.ass")

        fn = font_name.strip() if font_name.strip() else None

        res_path = speech_transcriber.generate_animated_ass_subtitles(
            words=words,
            output_path=output_ass_path,
            language=lang,
            style_mode=style_mode,
            aspect_ratio=aspect_ratio,
            words_per_card=words_per_card,
            font_name=fn,
            font_size=font_size,
            primary_color_hex=primary_color_hex,
            highlight_color_hex=highlight_color_hex
        )
        return json.dumps({"status": "success", "ass_path": res_path})
    except Exception as e:
        return json.dumps({"error": f"Animated subtitle generation failed: {str(e)}"})


@server.tool()
def video_burn_subtitles(video_path: str, subtitle_path: str, output_path: str = "", crf: int = 18) -> str:
    """
    Burns ASS or SRT subtitles permanently into a video using FFmpeg libass filter.
    """
    if not os.path.exists(video_path) or not os.path.exists(subtitle_path):
        return json.dumps({"error": "Video or Subtitle file does not exist."})

    if not output_path:
        stem = Path(video_path).stem
        output_path = str(Path(video_path).parent / f"{stem}_subtitled.mp4")

    try:
        out = speech_transcriber.burn_subtitles_to_video(video_path, subtitle_path, output_path, crf=crf)
        return json.dumps({"status": "success", "burned_video_path": out})
    except Exception as e:
        return json.dumps({"error": f"Subtitle burning failed: {str(e)}"})


@server.tool()
def video_auto_cut_silence(
    input_media: str,
    output_media: str = "",
    silence_thresh_db: float = -30.0,
    min_silence_sec: float = 0.5,
    pad_margin_sec: float = 0.12,
    render_video: bool = True
) -> str:
    """
    Detects speech and silence intervals, prunes dead air, creates a jump-cut manifest,
    and optionally renders the tightly-cut video with seamless audio transitions.
    """
    if not os.path.exists(input_media):
        return json.dumps({"error": f"Media '{input_media}' not found."})

    out_m = output_media.strip() if output_media.strip() else None

    try:
        res = auto_cutter.auto_cut_video_pipeline(
            input_media=input_media,
            output_media=out_m,
            silence_thresh_db=silence_thresh_db,
            min_silence_sec=min_silence_sec,
            pad_margin_sec=pad_margin_sec,
            render=render_video
        )
        return json.dumps(res, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Auto-cut failed: {str(e)}"})


@server.tool()
def video_enhance_audio(
    input_media: str,
    output_media: str = "",
    mode: str = "full_mastering",
    target_lufs: float = -16.0,
    denoise_amount: float = 12.0,
    presence_boost_db: float = 3.0
) -> str:
    """
    Applies multi-stage audio enhancement to vocal and video audio tracks.
    Modes:
      - 'full_mastering': Highpass (80Hz rumble cut) + Lowpass (12kHz hiss cut) +
        FFT de-noise (afftdn) + Vocal presence EQ (2.5kHz boost) +
        Dynamic leveling (dynaudnorm) + EBU R128 loudness (loudnorm).
      - 'voice_clarity': Highpass + Vocal presence EQ + Dynamic leveling + EBU R128.
      - 'denoise_only': Highpass + FFT de-noise + EBU R128.
      - 'normalize_only': Dynamic leveling + EBU R128.
    """
    if not os.path.exists(input_media):
        return json.dumps({"error": f"Input media '{input_media}' not found."})

    if not output_media:
        p = Path(input_media)
        output_media = str(p.parent / f"{p.stem}_enhanced{p.suffix}")

    try:
        out = audio_processor.enhance_audio(
            input_media=input_media,
            output_media=output_media,
            mode=mode,
            target_lufs=target_lufs,
            denoise_amount=denoise_amount,
            presence_boost_db=presence_boost_db
        )
        return json.dumps({"status": "success", "enhanced_audio_path": str(out)})
    except Exception as e:
        return json.dumps({"error": f"Audio enhancement failed: {str(e)}"})


@server.tool()
def video_normalize_audio(input_media: str, output_media: str, target_lufs: float = -16.0) -> str:
    """
    Applies dynamic audio normalization (dynaudnorm) and EBU R128 loudness normalization
    to level speech volume and compress sudden loud noise spikes.
    """
    if not os.path.exists(input_media):
        return json.dumps({"error": f"Input media '{input_media}' not found."})

    try:
        out = audio_processor.normalize_audio(input_media, output_media, target_lufs=target_lufs)
        return json.dumps({"status": "success", "output_path": str(out)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@server.tool()
def video_align_voiceover(video_path: str, voiceover_path: str, output_path: str) -> str:
    """
    Detects natural speech pauses in the voiceover audio and distributes silence padding
    to stretch and align the voiceover evenly across the video timeline.
    """
    if not os.path.exists(video_path) or not os.path.exists(voiceover_path):
        return json.dumps({"error": "Video or Voiceover file does not exist."})

    try:
        out = audio_processor.align_voiceover_spaced(video_path, voiceover_path, output_path)
        return json.dumps({"status": "success", "aligned_voiceover": str(out)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@server.tool()
def video_build_openshot_project(manifest_json_content: str, output_osp_path: str) -> str:
    """
    Generates a valid OpenShot 3.1.1 multi-track .osp project file.
    manifest_json_content: JSON string defining clips, layers, cuts, voiceover, and bgm.
    """
    try:
        manifest = json.loads(manifest_json_content)
        out = openshot_builder.create_openshot_project(manifest, output_osp_path)
        return json.dumps({"status": "success", "openshot_project": str(out)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@server.tool()
def video_export_render(input_video: str, output_path: str, preset: str = "youtube_1080p") -> str:
    """
    Renders video to final delivery formats using FFmpeg.
    Presets:
      - 'youtube_1080p': 1920x1080, 60fps, libx264 CRF 18, 320k AAC.
      - 'social_vertical': 1080x1920 (9:16 vertical crop), libx264 CRF 20.
    """
    if not os.path.exists(input_video):
        return json.dumps({"error": f"Input video '{input_video}' not found."})

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    if preset == "social_vertical":
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        cmd = ["ffmpeg", "-y", "-i", str(input_video), "-vf", vf, "-c:v", "libx264", "-crf", "20", "-c:a", "aac", "-b:a", "256k", str(out_p)]
    else:  # default youtube_1080p
        cmd = ["ffmpeg", "-y", "-i", str(input_video), "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k", str(out_p)]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return json.dumps({"status": "success", "rendered_file": str(out_p)})
    except subprocess.CalledProcessError as e:
        return json.dumps({"error": "FFmpeg render failed", "details": e.stderr.decode() if e.stderr else str(e)})


if __name__ == "__main__":
    server.run()
