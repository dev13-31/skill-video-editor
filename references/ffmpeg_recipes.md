# FFmpeg Recipes for Video Editor Skill

This document catalogs optimized FFmpeg filter commands used across the 9 editing phases.

---

## 1. Metadata Scanning (`ffprobe`)

### Quick JSON Probe (Duration, Codecs, Resolution, Creation Timestamp)
```bash
ffprobe -v quiet -print_format json -show_format -show_streams "input.mp4"
```

### Extract Creation Time
```bash
ffprobe -v quiet -select_streams v:0 -show_entries format_tags=creation_time -of default=noprint_wrappers=1:nokey=1 "input.mp4"
```

---

## 2. Frame Extraction for Visual Contact Sheet

### Extract 1 Thumbnail Every 10 Seconds
```bash
ffmpeg -i "input.mp4" -vf "fps=1/10,scale=320:-1" -vsync vfr "thumb_%03d.jpg"
```

### Extract Exact Timestamps Grid (Tile Filter)
```bash
ffmpeg -i "input.mp4" -vf "fps=1/5,scale=320:180,tile=4x4" -an "contact_sheet.jpg"
```

---

## 3. Audio Waveform Extraction

### Render High-Resolution Waveform PNG
```bash
ffmpeg -i "input.mp4" -filter_complex "aformat=channel_layouts=mono,showwavespic=s=1280x240:colors=#1db954" -frames:v 1 "waveform.png"
```

---

## 4. Visual Polish, Color Correction & Grading

### Contrast, Brightness & Saturation Adjustment
```bash
# Contrast 1.1, Brightness 0.05, Saturation 1.25
ffmpeg -i "input.mp4" -vf "eq=contrast=1.1:brightness=0.05:saturation=1.25" -c:a copy "polished.mp4"
```

### White Balance Drift Correction (Remove Blue Cast)
```bash
ffmpeg -i "input.mp4" -vf "colorbalance=rs=0.05:gs=0.0:bs=-0.08:rm=0.05:bm=-0.05" -c:a copy "balanced.mp4"
```

### Apply 3D LUT (.cube file)
```bash
ffmpeg -i "input.mp4" -vf "lut3d=file='cinematic.cube'" -c:a copy "graded.mp4"
```

---

## 5. Audio Normalization

### Dynamic Audio Normalization (`dynaudnorm`)
Levels quiet passages and compresses sudden loud spikes (wind, mic bumps):
```bash
ffmpeg -i "input.mp4" -af "dynaudnorm=f=150:g=15:p=0.95" -c:v copy "dynaud_output.mp4"
```

### Two-Pass EBU R128 Loudness Normalization (-16 LUFS for YouTube/Social)
```bash
# Pass 1: Measure
ffmpeg -i "input.mp4" -af "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json" -f null -

# Pass 2: Apply measured values
ffmpeg -i "input.mp4" -af "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=...:measured_TP=...:measured_LRA=...:measured_thresh=..." -c:v copy "lufs_output.mp4"
```

---

## 6. Fast Platform Export Profiles

### YouTube / Standard Web (1080p 60fps)
```bash
ffmpeg -i "input.mp4" -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -r 60 -c:a aac -b:a 320k "youtube_1080p.mp4"
```

### Instagram Reels / YouTube Shorts / TikTok (Vertical 1080x1920)
```bash
ffmpeg -i "input.mp4" -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" -c:v libx264 -preset medium -crf 20 -c:a aac -b:a 256k "vertical_short.mp4"
```

---

## 7. Intro & Outro Smooth Fades

### Slow Fade In as Main Video Starts (1.5s fade-in from black)
```bash
ffmpeg -i "main_video.mp4" -vf "fade=t=in:st=0:d=1.5" -af "afade=t=in:st=0:d=1.5" -c:v libx264 -c:a aac "faded_intro.mp4"
```

### Slow Fade Out at Ending (2.0s fade to black & silence, not abrupt)
```bash
# Assuming video duration is 180s, fade out starts at 178s:
ffmpeg -i "final_cut.mp4" -vf "fade=t=out:st=178:d=2.0" -af "afade=t=out:st=178:d=2.0" -c:v libx264 -c:a aac "smooth_ending.mp4"
```

---

## 8. Cut Transitions for Cuts > 10–20 Seconds

### Crossfade Transition Between Two Clips (`xfade`)
```bash
# Clip 1 duration: 15s. 1.0s crossfade starting at 14s:
ffmpeg -i "clip1.mp4" -i "clip2.mp4" -filter_complex "[0:v][1:v]xfade=transition=fade:duration=1:offset=14[v];[0:a][1:a]acrossfade=d=1[a]" -map "[v]" -map "[a]" "transition_output.mp4"
```

### Dip-to-Black Transition
```bash
# Fade out clip 1 at end (0.5s), fade in clip 2 at start (0.5s)
ffmpeg -i "clip1.mp4" -vf "fade=t=out:st=14.5:d=0.5" -c:a copy "c1_faded.mp4"
ffmpeg -i "clip2.mp4" -vf "fade=t=in:st=0:d=0.5" -c:a copy "c2_faded.mp4"
```

---

## 9. Still Photo Integration & Ken Burns Animation

### Convert Still Photo to 4-Second 1080p Video Slide with Subtle Zoom
```bash
ffmpeg -loop 1 -i "photo.jpg" -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,zoompan=z='min(zoom+0.0015,1.15)':d=120:s=1920x1080,fade=t=in:st=0:d=0.8,fade=t=out:st=3.2:d=0.8" -t 4 -c:v libx264 -pix_fmt yuv420p "photo_slide.mp4"
```

---

## 10. Text, Lower Thirds & Subtitle Overlays

### Burn Hardcoded Subtitles (.srt file)
```bash
ffmpeg -i "input.mp4" -vf "subtitles='captions.srt':force_style='FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3,Outline=2,Shadow=1,MarginV=30'" -c:a copy "subtitled_output.mp4"
```

### Dynamic Lower Third / Topic Heading (`drawtext`)
```bash
# Displays bold heading in lower-third between second 5.0 and 9.0:
ffmpeg -i "input.mp4" -vf "drawtext=text='EPISODE HIGHLIGHT':fontcolor=white:fontsize=36:box=1:boxcolor=black@0.6:boxborderw=10:x=(w-text_w)/2:y=h-text_h-80:enable='between(t,5,9)'" -c:a copy "title_overlay.mp4"
```

---

## 11. Extract Candidate Frame for YouTube Thumbnail (Nanobanana / Imagen)

### Extract High-Res Crisp Frame at Specific Climax / Reaction Timestamp
```bash
ffmpeg -ss 42.50 -i "source_video.mp4" -frames:v 1 -q:v 2 "thumbnail_candidate_frame.png"
```

---

## 12. Audio Sound Effects (SFX) Mixing

### Overlay Transition Whoosh / Impact SFX at Specific Second
```bash
# Plays transition whoosh at 14.5s mixed with base audio:
ffmpeg -i "video_with_audio.mp4" -i "sfx_whoosh.wav" -filter_complex "[1:a]adelay=14500|14500,volume=0.6[sfx];[0:a][sfx]amix=inputs=2:duration=first:dropout_transition=2[aout]" -map 0:v -map "[aout]" -c:v copy "with_sfx.mp4"
```

