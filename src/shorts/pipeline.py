import asyncio
import json
import logging
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, List, Optional

from pydantic import BaseModel

from shorts.captions import write_ass_file
from shorts.models import VoiceTrack
from shorts.render.compose import compose_video
from shorts.script_gen import GeneratedScript, generate_script
from shorts.sources import registry
from shorts.sources.base import ImageResult
from shorts.tts import generate_voice, mix_audio

logger = logging.getLogger(__name__)

class JobSpec(BaseModel):
    topic: str
    tone: str = "documentary"
    duration: int = 30
    
    # Voice
    voice_engine: str = "edge-tts"
    voice_lang: str = "en"
    voice_id: str = "en-US-ChristopherNeural"
    voice_rate: str = "+0%"
    voice_pitch: str = "+0Hz"
    
    # Visuals
    image_sources: List[str] = ["wikimedia", "openverse", "pexels", "pixabay", "unsplash"]
    subject_hint: str = "auto"
    motion_style: str = "auto"
    transition: str = "fade"
    allow_fallback: bool = True
    
    # Captions
    style: str = "karaoke"
    font_family: str = "Montserrat ExtraBold"
    font_size: int = 24
    primary_color: str = "&H00FFFFFF"
    highlight_color: str = "&H0000FFFF"
    outline_color: str = "&H00000000"
    vertical_position: int = 80
    uppercase: bool = True
    
    # Branding
    intro_path: Optional[str] = None
    outro_path: Optional[str] = None
    logo_path: Optional[str] = None
    logo_position: str = "top_right"
    logo_margin: int = 40
    logo_scale: float = 0.15
    logo_opacity: float = 1.0
    music_path: Optional[str] = None
    music_gain_db: int = -18
    
    # Quality
    render_preset: str = "fast"
    render_crf: int = 23
    render_fps: int = 30
    render_resolution: str = "1080x1920"
    keep_temp: bool = False

class ProgressEvent(BaseModel):
    stage: str
    pct: int
    message: str
    is_done: bool = False
    result_path: Optional[str] = None
    error: Optional[str] = None

class JobResult(BaseModel):
    job_id: str
    output_path: str
    sidecar_path: str
    script: GeneratedScript
    voice_track: VoiceTrack

async def download_asset(url: str, dest_path: Path):
    from shorts.http import fetch
    resp = await fetch("GET", url, use_cache=True)
    if resp.status_code == 200:
        with open(dest_path, "wb") as f:
            f.write(resp.content)
    else:
        raise ValueError(f"Failed to download image {url}")
    return dest_path

async def generate(job: JobSpec) -> AsyncGenerator[ProgressEvent, None]:
    job_id = uuid.uuid4().hex[:8]
    date_str = datetime.now().strftime("%Y%m%d")
    slug = "".join(c if c.isalnum() else "_" for c in job.topic)[:20].strip("_")
    
    run_dir = Path(f"runs/{job_id}")
    run_dir.mkdir(parents=True, exist_ok=True)
    
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    mp4_out = out_dir / f"{date_str}_{slug}_{job_id}.mp4"
    sidecar_out = out_dir / f"{date_str}_{slug}_{job_id}.json"
    
    try:
        # 1. Script
        yield ProgressEvent(stage="script", pct=5, message="Generating script...")
        script = await generate_script(topic=job.topic, tone=job.tone, duration_seconds=job.duration)
        yield ProgressEvent(stage="script", pct=20, message=f"Script generated with {len(script.scenes)} scenes.")
        
        # 2. Concurrently fetch TTS and Images
        yield ProgressEvent(stage="voice_and_images", pct=25, message="Generating TTS and fetching images concurrently...")
        
        async def fetch_scene_image(scene_idx, scene, sem):
            async with sem:
                imgs = await registry.fetch_images(
                    query=scene.image_query,
                    subject_type=scene.subject_type,
                    count=1,
                    orientation="portrait",
                    min_width=720
                )
                return scene_idx, imgs[0] if imgs else None

        sem = asyncio.Semaphore(4)
        image_tasks = [fetch_scene_image(i, scene, sem) for i, scene in enumerate(script.scenes)]
        
        tts_task = generate_voice(
            text=" ".join(s.narration for s in script.scenes),
            voice_id=job.voice_id,
            rate=job.voice_rate,
            pitch=job.voice_pitch
        )
        
        results = await asyncio.gather(tts_task, *image_tasks)
        
        voice_track: VoiceTrack = results[0]
        image_results = results[1:] 
        
        # Download images locally
        yield ProgressEvent(stage="voice_and_images", pct=40, message="Downloading assets locally...")
        dl_tasks = []
        local_scene_images = []
        manifest_images = []
        
        for idx, img_res in sorted(image_results, key=lambda x: x[0]):
            if not img_res:
                raise ValueError(f"Failed to find any valid image for scene {idx+1}")
                
            manifest_images.append(img_res)
            # Try to grab extension from URL, fallback to jpg
            ext = img_res.url.split("?")[0].split(".")[-1]
            if len(ext) > 4 or not ext.isalnum():
                ext = "jpg"
                
            dest = run_dir / f"scene_{idx}.{ext}"
            dl_tasks.append(download_asset(img_res.url, dest))
            local_scene_images.append(str(dest))
            
        await asyncio.gather(*dl_tasks)
        
        yield ProgressEvent(stage="voice", pct=50, message="TTS and assets ready.")
        
        # Mix Audio
        final_audio_path = voice_track.audio_path
        if job.music_path:
            yield ProgressEvent(stage="voice", pct=55, message="Mixing background music with sidechain ducking...")
            final_audio_path = await mix_audio(voice_track.audio_path, job.music_path, voice_track.duration, job.music_gain_db)

        # 3. Captions
        yield ProgressEvent(stage="captions", pct=60, message="Generating ASS subtitles...")
        ass_path = run_dir / "captions.ass"
        write_ass_file(
            voice_track.words, 
            ass_path, 
            style_name=job.style,
            font_family=job.font_family,
            font_size=job.font_size,
            primary_color=job.primary_color,
            highlight_color=job.highlight_color,
            outline_color=job.outline_color,
            vertical_position=job.vertical_position,
            uppercase=job.uppercase
        )
        
        # Calculate per-scene durations exactly matched to word timings
        scene_durations = []
        total_words_so_far = 0
        all_words = voice_track.words
        
        for i, scene in enumerate(script.scenes):
            scene_word_count = len(scene.narration.split())
            if total_words_so_far >= len(all_words):
                scene_durations.append(0.0)
                continue
                
            end_idx = min(total_words_so_far + scene_word_count - 1, len(all_words) - 1)
            
            start_time = all_words[total_words_so_far].start_time
            end_time = all_words[end_idx].end_time
            dur = end_time - start_time
            
            # Pad the duration to include the silent gap before the next sentence starts
            if i < len(script.scenes) - 1 and end_idx + 1 < len(all_words):
                next_start = all_words[end_idx + 1].start_time
                dur += (next_start - end_time)
            
            scene_durations.append(dur)
            total_words_so_far += scene_word_count
            
        # Guarantee audio/video mathematical lock
        if sum(scene_durations) < voice_track.duration:
            scene_durations[-1] += voice_track.duration - sum(scene_durations)

        # 4. Manifest
        manifest_path = run_dir / "manifest.json"
        registry.generate_manifest(manifest_images, manifest_path)

        # 5. Render
        yield ProgressEvent(stage="render", pct=70, message="Composing ffmpeg graph and rendering...")
        output_mp4 = str(mp4_out)
        
        compose_video(
            scene_images=local_scene_images,
            scene_durations=scene_durations,
            audio_path=final_audio_path,
            output_path=output_mp4,
            subtitles_path=str(ass_path),
            job_id=job_id,
            intro_path=job.intro_path,
            outro_path=job.outro_path,
            logo_path=job.logo_path,
            preset=job.render_preset,
            crf=job.render_crf,
            transition=job.transition
        )
        
        # 6. Verify (implicitly done in compose_video with ffprobe checks)
        yield ProgressEvent(stage="verify", pct=95, message="Verifying output...")
        
        sidecar_data = {
            "job_spec": job.model_dump(),
            "manifest": [m.model_dump() for m in manifest_images],
            "scene_durations": scene_durations,
            "timings": [w.model_dump() for w in voice_track.words],
        }
        with open(sidecar_out, "w", encoding="utf-8") as f:
            json.dump(sidecar_data, f, indent=2)

        yield ProgressEvent(stage="done", pct=100, message="Job complete", is_done=True, result_path=output_mp4)
        
    except Exception as e:
        logger.exception("Pipeline failed")
        error_log = run_dir / "error.log"
        with open(error_log, "w") as f:
            import traceback
            f.write(traceback.format_exc())
        yield ProgressEvent(stage="error", pct=100, message=str(e), is_done=True, error=str(e))
    finally:
        # Cleanup unless requested to keep or if it crashed
        if not job.keep_temp and not (run_dir / "error.log").exists():
            shutil.rmtree(run_dir, ignore_errors=True)
