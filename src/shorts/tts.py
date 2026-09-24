import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import edge_tts
from edge_tts import VoicesManager

from shorts.cache import cache
from shorts.config import settings
from shorts.models import VoiceTrack, WordTiming

logger = logging.getLogger(__name__)

# Fallback dependencies
try:
    from gtts import gTTS
except ImportError:
    gTTS = None

try:
    from faster_whisper import WhisperModel
    _whisper_model = None
except ImportError:
    WhisperModel = None


def _get_whisper() -> Any:
    global _whisper_model
    if WhisperModel is None:
        raise ImportError("faster-whisper is not installed. Use pip install .[whisper]")
    if _whisper_model is None:
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
    return _whisper_model


async def list_voices() -> Dict[str, List[Dict[str, str]]]:
    """
    Returns Edge-TTS voices grouped by (language, gender).
    Caches to disk.
    """
    cache_key = "edge_tts_voices"
    cached = cache.get_json("tts", cache_key)
    
    if cached:
        return cached

    voices_mgr = await VoicesManager.create()
    grouped: Dict[str, List[Dict[str, str]]] = {}
    
    for v in voices_mgr.voices:
        lang = v.get("Locale", "Unknown")
        gender = v.get("Gender", "Unknown")
        name = v.get("ShortName", "Unknown")
        friendly = v.get("FriendlyName", name)
        
        group_key = f"{lang} - {gender}"
        
        if group_key not in grouped:
            grouped[group_key] = []
            
        grouped[group_key].append({
            "name": name,
            "voice_id": name,
            "friendly_name": friendly
        })

    cache.set_json("tts", cache_key, grouped)
    return grouped


def _get_audio_duration(file_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


async def _generate_edge_tts(
    text: str, voice_id: str, rate: str, pitch: str, volume: str, output_path: Path
) -> VoiceTrack:
    communicate = edge_tts.Communicate(
        text, voice_id, rate=rate, pitch=pitch, volume=volume
    )
    
    words: List[WordTiming] = []
    
    # Run the stream and write to file
    with open(output_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # offset/duration are in 100-nanosecond units. 1e7 = 1 second.
                start = chunk["offset"] / 10_000_000.0
                duration = chunk["duration"] / 10_000_000.0
                words.append(
                    WordTiming(word=chunk["text"], start_time=start, end_time=start + duration)
                )

    duration_s = _get_audio_duration(output_path)
    
    return VoiceTrack(
        audio_path=str(output_path),
        duration=duration_s,
        words=words,
        engine_used="edge-tts",
        voice_id=voice_id,
        timings_source="tts"
    )


async def _align_whisper(audio_path: str) -> List[WordTiming]:
    model = _get_whisper()
    def _run():
        segments, _ = model.transcribe(audio_path, word_timestamps=True)
        words = []
        for segment in segments:
            for word in segment.words:
                words.append(
                    WordTiming(
                        word=word.word.strip(),
                        start_time=word.start,
                        end_time=word.end
                    )
                )
        return words
        
    return await asyncio.to_thread(_run)


async def _generate_piper(text: str, voice_id: str, output_path: Path) -> VoiceTrack:
    raise NotImplementedError("Piper TTS fallback not fully implemented")


async def _generate_kokoro(text: str, voice_id: str, output_path: Path) -> VoiceTrack:
    raise NotImplementedError("Kokoro-ONNX fallback not fully implemented")


async def _generate_gtts(text: str, voice_id: str, output_path: Path) -> VoiceTrack:
    if gTTS is None:
        raise ImportError("gTTS is not installed.")
    
    def _run():
        tts = gTTS(text, lang="en")
        tts.save(str(output_path))
        
    await asyncio.to_thread(_run)
    duration_s = _get_audio_duration(output_path)
    
    logger.info("Aligning gTTS audio with faster-whisper...")
    words = await _align_whisper(str(output_path))
    
    return VoiceTrack(
        audio_path=str(output_path),
        duration=duration_s,
        words=words,
        engine_used="gtts",
        voice_id=voice_id,
        timings_source="whisper"
    )


async def generate_voice(
    text: str, 
    voice_id: str = "en-US-ChristopherNeural", 
    rate: str = "+0%", 
    pitch: str = "+0Hz", 
    volume: str = "+0%"
) -> VoiceTrack:
    """
    Generates TTS using a cascade of engines.
    """
    import hashlib
    # Setup cache output path
    text_hash = hashlib.sha256(f"{text}{voice_id}{rate}{pitch}{volume}".encode()).hexdigest()
    output_path = settings.cache_dir / f"{text_hash}.mp3"
    
    # 1. Edge-TTS (Primary)
    try:
        logger.info(f"Generating TTS via Edge-TTS (voice: {voice_id})")
        return await _generate_edge_tts(text, voice_id, rate, pitch, volume, output_path)
    except Exception as e:
        logger.warning(f"Edge-TTS failed: {e}")

    # 2. Kokoro / Piper would go here
    
    # 3. gTTS (Last resort)
    try:
        logger.info("Falling back to gTTS...")
        return await _generate_gtts(text, "en", output_path)
    except Exception as e:
        logger.error(f"gTTS failed: {e}")
        
    raise RuntimeError("All TTS engines failed in the cascade.")


async def mix_audio(
    voice_path: str, 
    music_path: Optional[str], 
    voice_duration: float, 
    music_gain_db: int = -18
) -> str:
    """
    Mixes background music with the voice track, applying sidechain compression to duck the music.
    Returns the path to the mixed output.
    """
    if not music_path or not os.path.exists(music_path):
        return voice_path

    voice_path_obj = Path(voice_path)
    output_path = voice_path_obj.with_suffix(".mixed.mp3")
    
    # FFmpeg complex filter:
    # [0:a] = voice track
    # [1:a] = music track
    #
    # 1. Apply volume reduction to music -> [music]
    # 2. Sidechain compress [music] using [0:a] (voice) as control -> [ducked_music]
    # 3. Mix voice [0:a] and [ducked_music], cutting off at the shortest duration (voice) -> [aout]
    filter_complex = (
        f"[1:a]volume={music_gain_db}dB[music];"
        f"[music][0:a]sidechaincompress=threshold=0.06:ratio=4.0:attack=5:release=100[ducked_music];"
        f"[0:a][ducked_music]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", voice_path,
        "-i", music_path,
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-ac", "2",     # Ensure stereo output
        str(output_path)
    ]
    
    logger.info(f"Mixing voice with music (ducking {music_gain_db}dB)...")
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        logger.error(f"FFmpeg mixing failed: {stderr.decode()}")
        raise RuntimeError(f"FFmpeg mixing failed. Make sure ffmpeg is installed.")

    return str(output_path)
