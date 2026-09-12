# OpenShot Project (.osp) JSON Specification

OpenShot Video Editor project files (`.osp`) are JSON files specifying project metadata, imported media files, timeline clips, layers/tracks, markers, effects, and export presets.

## Core Schema Structure

```json
{
  "id": "UNIQUE_PROJECT_ID",
  "fps": { "num": 30, "den": 1 },
  "display_ratio": { "num": 16, "den": 9 },
  "pixel_ratio": { "num": 1, "den": 1 },
  "width": 1920,
  "height": 1080,
  "sample_rate": 48000,
  "channels": 2,
  "channel_layout": 3,
  "duration": 300.0,
  "scale": 15.0,
  "tick_pixels": 100,
  "playhead_position": 0,
  "profile": "HD 1080p 30 fps",
  "version": {
    "openshot-qt": "3.1.1",
    "libopenshot": "0.3.2"
  },
  "layers": [
    { "id": "L1", "number": 1000000, "y": 0, "label": "Main Visuals" },
    { "id": "L2", "number": 2000000, "y": 0, "label": "Voiceover" },
    { "id": "L3", "number": 3000000, "y": 0, "label": "BGM & Overlays" },
    { "id": "L4", "number": 4000000, "y": 0, "label": "Titles / Graphics" },
    { "id": "L5", "number": 5000000, "y": 0, "label": "Subtitles" }
  ],
  "files": [],
  "clips": [],
  "effects": [],
  "markers": [],
  "progress": [],
  "history": { "history": [], "current_index": 0 }
}
```

## `files` Entry Schema

Each imported media asset has an entry in `files`:

```json
{
  "id": "10_CHAR_ALPHANUM_OR_UUID",
  "path": "D:/path/to/clip.mp4",
  "media_type": "video",
  "vcodec": "h264",
  "acodec": "aac",
  "width": 1920,
  "height": 1080,
  "fps": { "num": 30, "den": 1 },
  "duration": 45.2,
  "video_length": 1356,
  "file_size": 52428800,
  "has_video": true,
  "has_audio": true,
  "sample_rate": 48000,
  "channels": 2,
  "channel_layout": 3
}
```

## `clips` Entry Schema

Clips place a portion of a file onto a timeline layer:

```json
{
  "id": "10_CHAR_CLIP_ID",
  "file_id": "10_CHAR_FILE_ID",
  "title": "clip_name.mp4",
  "layer": 1000000,
  "position": 0.0,
  "start": 0.0,
  "end": 15.0,
  "duration": 15.0,
  "alpha": { "Points": [{ "co": { "X": 1.0, "Y": 1.0 }, "interpolation": 2 }] },
  "volume": { "Points": [{ "co": { "X": 1.0, "Y": 1.0 }, "interpolation": 2 }] },
  "scale": 0,
  "scale_x": { "Points": [{ "co": { "X": 1.0, "Y": 1.0 }, "interpolation": 2 }] },
  "scale_y": { "Points": [{ "co": { "X": 1.0, "Y": 1.0 }, "interpolation": 2 }] },
  "location_x": { "Points": [{ "co": { "X": 1.0, "Y": 0.0 }, "interpolation": 2 }] },
  "location_y": { "Points": [{ "co": { "X": 1.0, "Y": 0.0 }, "interpolation": 2 }] },
  "has_audio": { "Points": [{ "co": { "X": 1.0, "Y": 1.0 }, "interpolation": 0 }] },
  "has_video": { "Points": [{ "co": { "X": 1.0, "Y": 1.0 }, "interpolation": 0 }] },
  "reader": { "...copy of file object from files array..." }
}
```

> [!IMPORTANT]
> **Mandatory `reader` Object**: Every clip MUST contain a `"reader"` dictionary mirroring the `file` object. OpenShot's WebKit Angular frontend calls `clip["reader"]["path"]` to render clip thumbnails. If `"reader"` is missing, OpenShot fails with `TypeError: undefined is not an object (evaluating 'clip["reader"]')`.

### Layer Stacking
- OpenShot stacks layers with higher numbers rendering **on top** of lower numbers.
- Layer 1000000: Base video clips / main story / still photo slides
- Layer 2000000: Voiceover audio track
- Layer 3000000: Background music (ducked) & Audio Effects (SFX: whooshes, risers)
- Layer 4000000: Title cards, graphics, lower thirds, topic text
- Layer 5000000: Subtitles / captions

---

## Fade Curves Specification (libopenshot Bezier Curves)

Smooth fade-in and fade-out are achieved by configuring multi-point Bezier keyframes on `"alpha"` (opacity) and `"volume"`.
Keyframe `X` coordinate represents the 1-based frame number within the clip:
- **Fade In (e.g. 1.5s at 30fps = 45 frames):**
  - Point 1: `{"co": {"X": 1.0, "Y": 0.0}}`
  - Point 2: `{"co": {"X": 45.0, "Y": 1.0}}`
- **Fade Out (e.g. 2.0s before clip end at frame 300):**
  - Point 3: `{"co": {"X": 240.0, "Y": 1.0}}`
  - Point 4: `{"co": {"X": 300.0, "Y": 0.0}}`

---

## Enhanced Manifest JSON Format (`openshot_builder.py`)

```json
{
  "width": 1920,
  "height": 1080,
  "fps": 30,
  "intro_fade_in": 1.5,
  "outro_fade_out": 2.0,
  "clips": [
    { "path": "D:/media/hook.mp4", "start": 0.0, "end": 12.0 },
    { "path": "D:/media/main_story.mp4", "start": 0.0, "end": 45.0, "is_main_after_intro": true },
    { "path": "D:/media/outro.mp4", "start": 0.0, "end": 15.0, "fade_out": 2.5 }
  ],
  "photos": [
    { "path": "D:/media/scenery.jpg", "position": 25.0, "duration": 4.0, "fade_in": 0.8, "fade_out": 0.8 }
  ],
  "voiceover": {
    "path": "D:/media/aligned_vo.wav",
    "position": 0.0
  },
  "bgm": {
    "path": "D:/media/ambient_bed.mp3",
    "volume": 0.20,
    "fade_in": 2.0,
    "fade_out": 2.0
  },
  "audio_effects": [
    { "path": "D:/sfx/whoosh.wav", "position": 12.0, "volume": 0.7 }
  ],
  "titles": [
    { "path": "D:/media/title_lower_third.png", "position": 13.5, "duration": 4.0, "fade_in": 0.5, "fade_out": 0.5 }
  ],
  "subtitles": [
    { "path": "D:/media/sub_01.png", "position": 2.0, "duration": 3.0 }
  ]
}
```

