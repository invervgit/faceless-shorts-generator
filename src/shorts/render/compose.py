import json
import logging
import os
import subprocess
from pathlib import Path
from typing import List, Optional

from shorts.config import settings
from shorts.render.kenburns import get_kenburns_filter
from shorts.render.overlays import get_logo_filter, get_normalization_filter, get_progress_bar_filter

logger = logging.getLogger(__name__)

def _get_media_info(file_path: str) -> dict:
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)

def _has_audio(file_path: str) -> bool:
    info = _get_media_info(file_path)
    return any(s.get("codec_type") == "audio" for s in info.get("streams", []))

def _get_duration(file_path: str) -> float:
    info = _get_media_info(file_path)
    return float(info.get("format", {}).get("duration", 0.0))

def compose_video(
    scene_images: List[str],
    scene_durations: List[float],
    audio_path: str,
    output_path: str,
    subtitles_path: str,
    job_id: str = "default",
    intro_path: Optional[str] = None,
    outro_path: Optional[str] = None,
    logo_path: Optional[str] = None,
    preset: str = "fast",
    crf: int = 23,
    transition: str = "fade",
    transition_duration: float = 0.3,
) -> str:
    """Builds and executes ONE ffmpeg command with a single complex filter graph."""
    inputs = []
    
    # Inputs 0 to N-1: Scene Images
    for img in scene_images:
        inputs.extend(["-loop", "1", "-framerate", "30", "-t", "60", "-i", img])
        
    # Input N: Main Audio
    audio_idx = len(scene_images)
    inputs.extend(["-i", audio_path])
    
    next_idx = audio_idx + 1
    
    intro_idx, outro_idx, logo_idx = -1, -1, -1
    if intro_path and os.path.exists(intro_path):
        intro_idx = next_idx
        inputs.extend(["-i", intro_path])
        next_idx += 1
        
    if outro_path and os.path.exists(outro_path):
        outro_idx = next_idx
        inputs.extend(["-i", outro_path])
        next_idx += 1
        
    if logo_path and os.path.exists(logo_path):
        logo_idx = next_idx
        inputs.extend(["-i", logo_path])
        next_idx += 1
        
    filter_complex = []
    
    # 1. Ken Burns
    scene_pads = []
    last_preset = None
    for i, duration in enumerate(scene_durations):
        # Extend video visual duration slightly for the crossfade overlap!
        pad_duration = duration + transition_duration if i < len(scene_durations) - 1 else duration
        f_str, last_preset = get_kenburns_filter(f"{i}:v", f"v{i}", pad_duration, exclude_preset=last_preset)
        filter_complex.append(f_str)
        scene_pads.append(f"v{i}")
        
    # 2. Xfade
    current_pad = scene_pads[0]
    total_offset = scene_durations[0]
    
    if len(scene_pads) > 1:
        for i in range(1, len(scene_pads)):
            out_pad = f"xfade{i}"
            filter_complex.append(f"[{current_pad}][{scene_pads[i]}]xfade=transition={transition}:duration={transition_duration}:offset={total_offset}[{out_pad}]")
            current_pad = out_pad
            if i < len(scene_durations) - 1:
                total_offset += scene_durations[i]

    # 3. ASS Subtitles (with escaped path)
    ass_escaped = subtitles_path.replace("\\", "/").replace(":", "\\:")
    out_pad = "with_subs"
    # Note: Fontsdir ensures Github Actions renders the exact same fonts as locally
    filter_complex.append(f"[{current_pad}]subtitles='{ass_escaped}':fontsdir=assets/fonts[{out_pad}]")
    current_pad = out_pad
    
    # 4. Logo Overlay
    if logo_idx != -1:
        out_pad = "with_logo"
        f_str = get_logo_filter(current_pad, f"{logo_idx}:v", out_pad)
        filter_complex.append(f_str)
        current_pad = out_pad
        
    # 5. Progress Bar
    out_pad = "with_progress"
    total_audio_duration = sum(scene_durations)
    filter_complex.append(get_progress_bar_filter(current_pad, out_pad, total_audio_duration))
    current_pad = out_pad
    
    # 6. Concat Intro/Outro
    video_concat_segments = []
    total_intro_audio_delay = 0.0
    
    if intro_idx != -1:
        intro_dur = _get_duration(intro_path)
        total_intro_audio_delay += intro_dur
        filter_complex.append(get_normalization_filter(f"{intro_idx}:v", "intro_v"))
        video_concat_segments.append("[intro_v]")
        
    video_concat_segments.append(f"[{current_pad}]")
    
    if outro_idx != -1:
        filter_complex.append(get_normalization_filter(f"{outro_idx}:v", "outro_v"))
        video_concat_segments.append("[outro_v]")
        
    if len(video_concat_segments) > 1:
        out_pad = "final_v"
        concat_str = "".join(video_concat_segments)
        filter_complex.append(f"{concat_str}concat=n={len(video_concat_segments)}:v=1:a=0[{out_pad}]")
        current_pad = out_pad
        
        # Audio delay handling: If we have an intro, delay the main audio to sync!
        if total_intro_audio_delay > 0:
            delay_ms = int(total_intro_audio_delay * 1000)
            filter_complex.append(f"[{audio_idx}:a]adelay=delays={delay_ms}|{delay_ms}:all=1[final_a]")
            audio_pad = "[final_a]"
        else:
            audio_pad = f"{audio_idx}:a"
    else:
        out_pad = current_pad
        audio_pad = f"{audio_idx}:a"

    filter_script = ";\n".join(filter_complex)
    
    # Ensure logs dir exists
    log_path = Path(f"logs/ffmpeg_{job_id}.txt")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "ffmpeg", "-y",
    ] + inputs + [
        "-filter_complex", filter_script,
        "-map", f"[{out_pad}]",
        "-map", audio_pad,
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-r", "30",
        output_path
    ]

    with open(log_path, "w") as f:
        f.write(" ".join(cmd) + "\n\n")
        f.write("FILTER COMPLEX:\n" + filter_script)

    logger.info(f"Running FFmpeg graph for job {job_id}...")
    
    # Stream stderr to parse progress and collect errors
    process = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True)
    
    stderr_lines = []
    for line in process.stderr:
        stderr_lines.append(line)
        # Progress parsing happens here in a live environment
        pass
        
    process.wait()
    
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("\n\nSTDERR:\n" + "".join(stderr_lines))
        
    if process.returncode != 0:
        error_tail = "".join(stderr_lines[-20:])
        raise RuntimeError(f"FFmpeg failed with code {process.returncode}. Last error lines:\n{error_tail}\nSee {log_path} for details.")
        
    # 7. Validate output
    out_dur = _get_duration(output_path)
    out_has_audio = _has_audio(output_path)
    
    expected_dur = total_audio_duration + total_intro_audio_delay
    if outro_idx != -1:
        expected_dur += _get_duration(outro_path)
        
    if abs(out_dur - expected_dur) > 0.6:
        logger.warning(f"Output duration {out_dur}s differs significantly from expected {expected_dur}s.")
        
    if not out_has_audio:
        raise ValueError("Generated video has no audio stream! Graph disconnected.")
        
    logger.info(f"Successfully generated {output_path}")
    return output_path
