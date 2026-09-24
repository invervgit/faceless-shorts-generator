import json
from pathlib import Path

def get_normalization_filter(pad_in: str, pad_out: str, width: int = 1080, height: int = 1920, fps: int = 30) -> str:
    """Normalizes any video to the exact resolution and framerate, padding if necessary."""
    return f"[{pad_in}]scale={width}x{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},setsar=1[{pad_out}]"

def get_logo_filter(vid_in: str, logo_in: str, pad_out: str, position: str = "top_right", margin: int = 40, opacity: float = 1.0, scale: float = 0.15) -> str:
    """Overlays a logo at one of 9 anchor positions with scaling and opacity."""
    logo_w = int(1080 * scale)
    logo_prep = f"[{logo_in}]scale={logo_w}:-1,format=rgba,colorchannelmixer=aa={opacity}[logo_prepped];"
    
    x = str(margin)
    y = str(margin)
    
    if "right" in position:
        x = f"W-w-{margin}"
    elif "center" in position and "left" not in position and "right" not in position:
        x = "(W-w)/2"
        
    if "bottom" in position:
        y = f"H-h-{margin}"
    elif "center" in position and "top" not in position and "bottom" not in position:
        y = "(H-h)/2"
            
    overlay = f"[{vid_in}][logo_prepped]overlay=x={x}:y={y}[{pad_out}]"
    return logo_prep + overlay

def get_progress_bar_filter(vid_in: str, pad_out: str, duration: float) -> str:
    """Progress bar disabled due to FFmpeg drawbox limitations."""
    return f"[{vid_in}]null[{pad_out}]"

def generate_attribution_frame(manifest_path: str, output_path: str, width: int = 1080, height: int = 1920) -> str:
    """Auto-generates a credits card from manifest.json using Pillow."""
    from PIL import Image, ImageDraw, ImageFont
    
    manifest = Path(manifest_path)
    if not manifest.exists():
        return ""
        
    data = json.loads(manifest.read_text(encoding="utf-8"))
    
    img = Image.new("RGB", (width, height), color=(15, 15, 20))
    draw = ImageDraw.Draw(img)
    
    try:
        font_path = "assets/fonts/Montserrat-ExtraBold.ttf"
        title_font = ImageFont.truetype(font_path, 40)
        body_font = ImageFont.truetype(font_path, 24)
    except IOError:
        title_font = ImageFont.load_default()
        body_font = ImageFont.load_default()
        
    draw.text((100, 100), "CREDITS & ATTRIBUTIONS", font=title_font, fill=(255, 255, 255))
    
    y = 200
    for item in data:
        text = f"{item['source'].upper()}: {item['attribution']} ({item['license']})"
        draw.text((100, y), text, font=body_font, fill=(200, 200, 200))
        y += 40
        if y > height - 100:
            break
            
    img.save(output_path)
    return output_path
