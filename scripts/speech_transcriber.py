"""
Multilingual Speech-to-Text (STT) and Synchronized Animated Subtitles Engine
Powered by faster-whisper and FFmpeg libass.

Features:
1. Multilingual transcription (English, Hindi, Spanish, French, etc.)
2. Word-level timestamp extraction
3. Subtitle exports: JSON, SRT, VTT, and stylized ASS (Advanced SubStation Alpha)
4. Animated word-level karaoke / pop-highlight subtitles in sync with spoken words
5. Direct burning into video via FFmpeg libass filter
"""

import argparse
import json
import math
import os
import re
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


def format_timestamp_srt(seconds: float) -> str:
    """Converts seconds to SRT timestamp: HH:MM:SS,mmm"""
    if seconds < 0:
        seconds = 0
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    msecs = int(round((seconds - int(seconds)) * 1000))
    if msecs >= 1000:
        msecs = 999
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{msecs:03d}"


def format_timestamp_vtt(seconds: float) -> str:
    """Converts seconds to WebVTT timestamp: HH:MM:SS.mmm"""
    if seconds < 0:
        seconds = 0
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    msecs = int(round((seconds - int(seconds)) * 1000))
    if msecs >= 1000:
        msecs = 999
    return f"{hrs:02d}:{mins:02d}:{secs:02d}.{msecs:03d}"


def format_timestamp_ass(seconds: float) -> str:
    """Converts seconds to ASS timestamp: H:MM:SS.cs (centiseconds)"""
    if seconds < 0:
        seconds = 0
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    csecs = int(round((seconds - int(seconds)) * 100))
    if csecs >= 100:
        csecs = 99
    return f"{hrs}:{mins:02d}:{secs:02d}.{csecs:02d}"


def hex_rgb_to_ass_bgr(hex_str: str) -> str:
    """
    Converts #RRGGBB or RRGGBB into ASS &H00BBGGRR& format.
    """
    clean = hex_str.strip().lstrip("#").lstrip("&H")
    if len(clean) == 6:
        r = clean[0:2]
        g = clean[2:4]
        b = clean[4:6]
        return f"&H00{b}{g}{r}&"
    return "&H00FFFFFF&"


def get_optimal_font_for_language(language_code: str) -> str:
    """
    Selects the best installed font for target language script.
    Nirmala UI provides native Devanagari (Hindi, Marathi), Bengali, Tamil, Telugu, Gurmukhi.
    Arial / Segoe UI Black for Latin / English.
    """
    indic_langs = {"hi", "hindi", "bn", "bengali", "ta", "tamil", "te", "telugu", "mr", "marathi", "pa", "punjabi", "gu", "gujarati"}
    if language_code and language_code.lower() in indic_langs:
        return "Nirmala UI"
    return "Arial"


class SpeechTranscriber:
    """
    Wrapper around faster-whisper for speech transcription and subtitle generation.
    """
    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            print(f"Loading faster-whisper model '{self.model_size}' on {self.device} ({self.compute_type})...")
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        return self._model

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        task: str = "transcribe",
        vad_filter: bool = True,
        min_silence_duration_ms: int = 400,
    ) -> Dict[str, Any]:
        """
        Transcribes audio/video file with word-level timestamps.
        
        Args:
            audio_path: Path to audio or video file.
            language: Language code ('en', 'hi', 'es', etc.) or None for automatic language detection.
            task: 'transcribe' or 'translate' (translates to English).
            vad_filter: Enable Voice Activity Detection to remove background noise/silence.
            min_silence_duration_ms: Minimum silence duration for VAD segmentation.
        """
        p = Path(audio_path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Media file not found: {audio_path}")

        lang = language.lower().strip() if language else None
        if lang in ["auto", "none", ""]:
            lang = None

        vad_params = dict(min_silence_duration_ms=min_silence_duration_ms) if vad_filter else None

        segments_iter, info = self.model.transcribe(
            str(p),
            language=lang,
            task=task,
            word_timestamps=True,
            vad_filter=vad_filter,
            vad_parameters=vad_params,
        )

        detected_lang = info.language
        lang_prob = round(info.language_probability, 4)
        duration = round(info.duration, 2)

        segments_list = []
        words_list = []
        full_text_parts = []

        for seg in segments_iter:
            seg_text = seg.text.strip()
            full_text_parts.append(seg_text)
            seg_dict = {
                "id": seg.id,
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg_text,
                "words": []
            }
            if seg.words:
                for w in seg.words:
                    word_clean = w.word.strip()
                    if not word_clean:
                        continue
                    w_dict = {
                        "word": word_clean,
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                        "probability": round(w.probability, 4)
                    }
                    seg_dict["words"].append(w_dict)
                    words_list.append(w_dict)
            segments_list.append(seg_dict)

        full_text = " ".join(full_text_parts)

        return {
            "source_file": str(p),
            "detected_language": detected_lang,
            "language_probability": lang_prob,
            "duration": duration,
            "full_text": full_text,
            "segment_count": len(segments_list),
            "word_count": len(words_list),
            "segments": segments_list,
            "words": words_list
        }


def export_srt(segments: List[Dict[str, Any]], output_path: str) -> str:
    """Exports segments to standard SRT file."""
    lines = []
    for idx, seg in enumerate(segments, 1):
        start_str = format_timestamp_srt(seg["start"])
        end_str = format_timestamp_srt(seg["end"])
        text = seg["text"]
        lines.append(f"{idx}\n{start_str} --> {end_str}\n{text}\n")

    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text("\n".join(lines), encoding="utf-8")
    return str(out_p)


def export_vtt(segments: List[Dict[str, Any]], output_path: str) -> str:
    """Exports segments to WebVTT file."""
    lines = ["WEBVTT\n"]
    for idx, seg in enumerate(segments, 1):
        start_str = format_timestamp_vtt(seg["start"])
        end_str = format_timestamp_vtt(seg["end"])
        text = seg["text"]
        lines.append(f"{start_str} --> {end_str}\n{text}\n")

    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text("\n".join(lines), encoding="utf-8")
    return str(out_p)


def generate_animated_ass_subtitles(
    words: List[Dict[str, Any]],
    output_path: str,
    language: str = "en",
    style_mode: str = "highlight",
    aspect_ratio: str = "16:9",
    words_per_card: int = 4,
    font_name: Optional[str] = None,
    font_size: int = 0,
    primary_color_hex: str = "#FFFFFF",
    highlight_color_hex: str = "#FFD700",
    outline_color_hex: str = "#000000",
    outline_width: int = 3,
    shadow_depth: int = 2,
    margin_v: int = 45,
) -> str:
    r"""
    Generates high-retention animated subtitles (.ass) in sync with spoken words.
    
    Modes:
      - 'highlight': Words appear in groups of `words_per_card`. As each word is spoken,
        it pops into `highlight_color` (e.g. Bright Gold) while surrounding words stay crisp white.
      - 'karaoke': Words fill smoothly from left to right using ASS karaoke timing tags (\kf).
      - 'clean': Synchronized punchy cards without active color cycling.
      
    Aspect ratio:
      - '16:9': 1920x1080 resolution, optimal for YouTube / Desktop.
      - '9:16': 1080x1920 resolution, optimal for Reels / Shorts / TikTok.
    """
    if not words:
        raise ValueError("Cannot generate subtitles: words list is empty.")

    is_vertical = aspect_ratio == "9:16"
    res_x = 1080 if is_vertical else 1920
    res_y = 1920 if is_vertical else 1080

    selected_font = font_name or get_optimal_font_for_language(language)
    if font_size <= 0:
        font_size = 56 if is_vertical else 44

    primary_bgr = hex_rgb_to_ass_bgr(primary_color_hex)
    highlight_bgr = hex_rgb_to_ass_bgr(highlight_color_hex)
    outline_bgr = hex_rgb_to_ass_bgr(outline_color_hex)
    back_bgr = "&H80000000&"  # 50% translucent black box shadow

    indic_langs = {"hi", "hindi", "bn", "bengali", "ta", "tamil", "te", "telugu", "mr", "marathi", "pa", "punjabi", "gu", "gujarati"}
    is_indic = bool(language and language.lower() in indic_langs)
    bold_val = 0 if is_indic else -1

    # ASS Header
    ass_content = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {res_x}",
        f"PlayResY: {res_y}",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{selected_font},{font_size},{primary_bgr},{highlight_bgr},{outline_bgr},{back_bgr},{bold_val},0,0,0,100,100,0,0,1,{outline_width},{shadow_depth},2,30,30,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    # Group words into chunks / cards
    chunks: List[List[Dict[str, Any]]] = []
    current_chunk = []
    
    for i, w in enumerate(words):
        current_chunk.append(w)
        # Check if chunk should close: reaches word count, or long pause (>0.7s) to next word, or punctuation ending
        has_pause = False
        if i + 1 < len(words):
            if words[i + 1]["start"] - w["end"] > 0.7:
                has_pause = True

        ends_sentence = any(w["word"].endswith(punct) for punct in [".", "?", "!", "|", "।"])

        if len(current_chunk) >= words_per_card or has_pause or ends_sentence:
            chunks.append(current_chunk)
            current_chunk = []

    if current_chunk:
        chunks.append(current_chunk)

    # Generate Dialogue Events
    for chunk in chunks:
        if not chunk:
            continue
        chunk_start = chunk[0]["start"]
        chunk_end = chunk[-1]["end"]

        if style_mode == "highlight":
            # For each word in the chunk, create a sub-interval where that specific word is highlighted
            for w_idx, active_word in enumerate(chunk):
                w_start = active_word["start"]
                # Active word end: either when next word starts, or when this word ends
                if w_idx + 1 < len(chunk):
                    w_end = min(chunk[w_idx + 1]["start"], active_word["end"] + 0.3)
                else:
                    w_end = active_word["end"]

                if w_end <= w_start:
                    w_end = w_start + 0.1

                # Construct phrase text with active word highlighted
                parts = []
                for idx, w in enumerate(chunk):
                    raw_text = w["word"]
                    if is_indic:
                        if idx == w_idx:
                            parts.append(f"{{\\c{highlight_bgr}}}{raw_text}")
                        else:
                            parts.append(f"{{\\c{primary_bgr}}}{raw_text}")
                    else:
                        if idx == w_idx:
                            # Highlight active word with bright color and slight pop
                            parts.append(f"{{\\c{highlight_bgr}\\fscx112\\fscy112}}{raw_text}{{\\r}}")
                        else:
                            parts.append(f"{{\\c{primary_bgr}}}{raw_text}{{\\r}}")

                event_text = " ".join(parts)
                start_str = format_timestamp_ass(w_start)
                end_str = format_timestamp_ass(w_end)
                ass_content.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{event_text}")

        elif style_mode == "karaoke":
            # Uses ASS \kf (smooth sweep fill) tags
            karaoke_parts = []
            for w in chunk:
                dur_cs = int(round((w["end"] - w["start"]) * 100))
                dur_cs = max(1, dur_cs)
                karaoke_parts.append(f"{{\\kf{dur_cs}}}{w['word']}")
            event_text = " ".join(karaoke_parts)
            start_str = format_timestamp_ass(chunk_start)
            end_str = format_timestamp_ass(chunk_end)
            ass_content.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{event_text}")

        else:  # clean mode
            phrase_text = " ".join(w["word"] for w in chunk)
            start_str = format_timestamp_ass(chunk_start)
            end_str = format_timestamp_ass(chunk_end)
            ass_content.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{phrase_text}")

    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text("\n".join(ass_content), encoding="utf-8")
    return str(out_p)


def burn_subtitles_to_video(
    video_path: str,
    subtitle_path: str,
    output_path: str,
    crf: int = 18,
    preset: str = "medium",
) -> str:
    """
    Renders/burns ASS or SRT subtitles into the video file using FFmpeg's libass filter.
    """
    in_v = Path(video_path).resolve()
    in_sub = Path(subtitle_path).resolve()
    out_v = Path(output_path).resolve()

    if not in_v.exists():
        raise FileNotFoundError(f"Input video not found: {video_path}")
    if not in_sub.exists():
        raise FileNotFoundError(f"Subtitle file not found: {subtitle_path}")

    out_v.parent.mkdir(parents=True, exist_ok=True)

    # Windows path escaping for FFmpeg filtergraph:
    # Colon ':' and backslashes '\' in path must be escaped
    escaped_sub = str(in_sub).replace("\\", "/").replace(":", "\\:")

    filter_str = f"subtitles='{escaped_sub}':charenc=UTF-8:shaping=1"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(in_v),
        "-vf", filter_str,
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(out_v)
    ]

    print(f"Burning subtitles: {in_sub.name} -> {out_v.name}...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg subtitle burn failed:\n{res.stderr}")

    return str(out_v)


def run_full_stt_pipeline(
    media_path: str,
    output_dir: Optional[str] = None,
    model_size: str = "base",
    language: Optional[str] = None,
    burn_into_video: bool = False,
    burned_video_output: Optional[str] = None,
    aspect_ratio: str = "16:9",
    style_mode: str = "highlight",
    words_per_card: int = 4,
    highlight_color_hex: str = "#FFD700"
) -> Dict[str, Any]:
    """
    Executes end-to-end STT, multi-format export, and optional subtitle burning.
    """
    src = Path(media_path).resolve()
    target_dir = Path(output_dir).resolve() if output_dir else src.parent / "subtitles"
    target_dir.mkdir(parents=True, exist_ok=True)

    stem = src.stem

    transcriber = SpeechTranscriber(model_size=model_size)
    result = transcriber.transcribe(str(src), language=language)

    lang = result["detected_language"]

    # Export formats
    json_path = str(target_dir / f"{stem}_transcript.json")
    srt_path = str(target_dir / f"{stem}.srt")
    vtt_path = str(target_dir / f"{stem}.vtt")
    ass_path = str(target_dir / f"{stem}_animated.ass")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    export_srt(result["segments"], srt_path)
    export_vtt(result["segments"], vtt_path)

    if result["words"]:
        generate_animated_ass_subtitles(
            words=result["words"],
            output_path=ass_path,
            language=lang,
            style_mode=style_mode,
            aspect_ratio=aspect_ratio,
            words_per_card=words_per_card,
            highlight_color_hex=highlight_color_hex
        )
    else:
        ass_path = None

    response = {
        "status": "success",
        "source": str(src),
        "detected_language": lang,
        "language_probability": result["language_probability"],
        "duration": result["duration"],
        "full_text": result["full_text"],
        "segment_count": result["segment_count"],
        "word_count": result["word_count"],
        "json_path": json_path,
        "srt_path": srt_path,
        "vtt_path": vtt_path,
        "ass_path": ass_path,
    }

    if burn_into_video and ass_path:
        out_vid = burned_video_output or str(target_dir / f"{stem}_subtitled.mp4")
        burned_path = burn_subtitles_to_video(str(src), ass_path, out_vid)
        response["burned_video_path"] = burned_path

    return response


def main():
    parser = argparse.ArgumentParser(description="Multilingual Speech-to-Text and Animated Subtitles Engine")
    parser.add_argument("media", help="Path to video or audio file")
    parser.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium", "large-v3"], help="Whisper model size")
    parser.add_argument("--lang", default=None, help="Language code (e.g. en, hi, es). Default: auto-detect")
    parser.add_argument("--out-dir", default=None, help="Directory to save subtitle files")
    parser.add_argument("--style", default="highlight", choices=["highlight", "karaoke", "clean"], help="Animated subtitle style")
    parser.add_argument("--ratio", default="16:9", choices=["16:9", "9:16"], help="Aspect ratio for font scaling")
    parser.add_argument("--words-per-card", type=int, default=4, help="Number of words per subtitle card")
    parser.add_argument("--highlight-color", default="#FFD700", help="Hex color for active spoken word (e.g. #FFD700)")
    parser.add_argument("--burn", action="store_true", help="Burn animated subtitles directly into the video")
    parser.add_argument("--burn-out", default=None, help="Output path for burned video")
    args = parser.parse_args()

    res = run_full_stt_pipeline(
        media_path=args.media,
        output_dir=args.out_dir,
        model_size=args.model,
        language=args.lang,
        burn_into_video=args.burn,
        burned_video_output=args.burn_out,
        aspect_ratio=args.ratio,
        style_mode=args.style,
        words_per_card=args.words_per_card,
        highlight_color_hex=args.highlight_color
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
