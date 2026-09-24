import logging
import re
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from shorts.config import settings
from shorts.models import WordTiming

logger = logging.getLogger(__name__)


def load_styles(config_path: Optional[Path] = None) -> Dict[str, Any]:
    if config_path is None:
        config_path = Path("config/caption_styles.yaml")
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def format_ass_time(seconds: float) -> str:
    """Format seconds into ASS time format: H:MM:SS.cs"""
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    centisecs = int(round((seconds - total_seconds) * 100))
    # Keep centisecs within 0-99 boundary to avoid 100 overflow
    if centisecs == 100:
        centisecs = 99
    return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"


def escape_ass(text: str) -> str:
    """Escape ASS special characters."""
    text = text.replace('{', '｛').replace('}', '｝')
    return text


class ASSGenerator:
    def __init__(self, width: int = 1080, height: int = 1920):
        self.width = width
        self.height = height
        self.styles_config = load_styles()

    def generate(
        self,
        words: List[WordTiming],
        style_name: str = "karaoke",
        **style_overrides
    ) -> str:
        """
        Generates ASS subtitle content from WordTimings.
        
        Supported styles:
        - karaoke: Highlights word-by-word sequentially using \\k tags.
        - word: One word on screen at a time.
        - phrase: Full phrase on screen static.
        - typewriter: Words appear progressively without highlight animations.
        """
        # Load defaults for the style
        config = self.styles_config.get(style_name, self.styles_config.get("karaoke", {}))
        
        # Merge overrides
        font_family = style_overrides.get("font_family", config.get("font_family", "Montserrat ExtraBold"))
        font_size = style_overrides.get("font_size", config.get("font_size", 24))
        primary_color = style_overrides.get("primary_color", config.get("primary_color", "&H00FFFFFF"))
        highlight_color = style_overrides.get("highlight_color", config.get("highlight_color", "&H0000FFFF"))
        outline_color = style_overrides.get("outline_color", config.get("outline_color", "&H00000000"))
        vertical_position = style_overrides.get("vertical_position", config.get("vertical_position", 80))
        uppercase = style_overrides.get("uppercase", config.get("uppercase", True))
        max_words_per_chunk = style_overrides.get("max_words_per_chunk", config.get("max_words_per_chunk", 4))
        
        # Calculate Y position based on frame height (18% to 78% safe area)
        clamped_pos = max(18, min(78, vertical_position))
        margin_v = int((self.height * clamped_pos) / 100)
        
        lines = []
        lines.append("[Script Info]")
        lines.append("ScriptType: v4.00+")
        lines.append(f"PlayResX: {self.width}")
        lines.append(f"PlayResY: {self.height}")
        lines.append("WrapStyle: 1")
        lines.append("")
        lines.append("[V4+ Styles]")
        lines.append("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")
        
        # For ASS Karaoke (\\k):
        # PrimaryColour is the final/highlighted color (\\1c)
        # SecondaryColour is the initial/unhighlighted color (\\2c)
        lines.append(f"Style: BaseStyle,{font_family},{font_size},{highlight_color},{primary_color},{outline_color},&H00000000,-1,0,0,0,100,100,0,0,1,4,2,8,20,20,{margin_v},1")
        lines.append("")
        lines.append("[Events]")
        lines.append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text")

        if not words:
            return "\n".join(lines)

        chunks = self._chunk_words(words, max_words_per_chunk)

        for chunk in chunks:
            start_time = chunk[0].start_time
            end_time = chunk[-1].end_time
            start_ass = format_ass_time(start_time)
            end_ass = format_ass_time(end_time)
            
            if style_name == "karaoke":
                dialogue_text = ""
                last_end = start_time
                for i, w in enumerate(chunk):
                    # Handle any gap before this word
                    gap = w.start_time - last_end
                    if gap > 0.01:
                        gap_cs = int(round(gap * 100))
                        dialogue_text += f"{{\\k{gap_cs}}} "
                    elif i > 0:
                        dialogue_text += " "
                        
                    duration_cs = int(round((w.end_time - w.start_time) * 100))
                    text = w.word.upper() if uppercase else w.word
                    text = escape_ass(text)
                    
                    dialogue_text += f"{{\\k{duration_cs}}}{text}"
                    last_end = w.end_time
                    
                lines.append(f"Dialogue: 0,{start_ass},{end_ass},BaseStyle,,0,0,0,,{dialogue_text}")

            elif style_name == "word":
                for w in chunk:
                    w_start = format_ass_time(w.start_time)
                    w_end = format_ass_time(w.end_time)
                    text = w.word.upper() if uppercase else w.word
                    text = escape_ass(text)
                    lines.append(f"Dialogue: 0,{w_start},{w_end},BaseStyle,,0,0,0,,{text}")

            elif style_name == "phrase":
                text = " ".join([w.word for w in chunk])
                if uppercase: text = text.upper()
                text = escape_ass(text)
                lines.append(f"Dialogue: 0,{start_ass},{end_ass},BaseStyle,,0,0,0,,{text}")

            elif style_name == "typewriter":
                # Progressively reveal words across the duration of the chunk
                revealed = []
                for i in range(len(chunk)):
                    w_start = format_ass_time(chunk[i].start_time)
                    w_end = format_ass_time(chunk[i+1].start_time) if i < len(chunk)-1 else format_ass_time(chunk[-1].end_time)
                    revealed.append(chunk[i].word)
                    text = " ".join(revealed)
                    if uppercase: text = text.upper()
                    text = escape_ass(text)
                    lines.append(f"Dialogue: 0,{w_start},{w_end},BaseStyle,,0,0,0,,{text}")

        return "\n".join(lines)

    def _chunk_words(self, words: List[WordTiming], max_words: int) -> List[List[WordTiming]]:
        chunks = []
        current_chunk = []
        
        # Punctuation that forces a chunk break
        break_chars = {'.', ',', '!', '?', ';', ':'}

        for w in words:
            current_chunk.append(w)
            
            # Check if word ends with terminal punctuation
            has_punctuation = any(c in break_chars for c in w.word)
            
            if len(current_chunk) >= max_words or has_punctuation:
                chunks.append(current_chunk)
                current_chunk = []
                
        if current_chunk:
            chunks.append(current_chunk)
            
        return chunks


def write_ass_file(words: List[WordTiming], output_path: Path, style_name: str = "karaoke", **overrides):
    """Convenience method to generate and write an ASS file directly."""
    generator = ASSGenerator()
    ass_content = generator.generate(words, style_name, **overrides)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_content)
