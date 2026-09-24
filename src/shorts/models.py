from typing import List, Optional

from pydantic import BaseModel, Field


class WordTiming(BaseModel):
    """Timing for a single spoken word for karaoke captions."""
    word: str
    start_time: float
    end_time: float


class VoiceTrack(BaseModel):
    """Represents a generated TTS voiceover track."""
    audio_path: str
    duration: float
    words: List[WordTiming] = Field(default_factory=list)
    engine_used: str = "unknown"
    voice_id: str = "unknown"
    timings_source: str = "tts"


class Scene(BaseModel):
    """A scene in the video, usually mapping to a sentence or phrase."""
    text: str
    image_url: Optional[str] = None
    image_path: Optional[str] = None
    voice_track: Optional[VoiceTrack] = None
    pan_direction: Optional[str] = None


class Script(BaseModel):
    """The complete generated script for the short."""
    topic: str
    scenes: List[Scene]
    music_path: Optional[str] = None
