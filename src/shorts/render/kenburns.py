import random
from typing import Tuple

PRESETS = [
    "zoom_in", "zoom_out", "pan_left", "pan_right", 
    "pan_up", "pan_down", "zoom_in_pan_left", "static"
]

def get_kenburns_filter(pad_in: str, pad_out: str, duration: float, fps: int = 30, exclude_preset: str = None) -> Tuple[str, str]:
    """
    Returns the ffmpeg filter string for a Ken Burns effect and the preset used.
    
    - Pre-scales source to 2x output (2160x3840) BEFORE zoompan to eliminate visible jitter.
    - Uses exact frame counts for duration.
    """
    choices = [p for p in PRESETS if p != exclude_preset]
    preset = random.choice(choices)
    
    # Pre-scale to 2x output (2160x3840) to fix zoompan jitter
    base = f"[{pad_in}]scale=2160x3840:force_original_aspect_ratio=increase,crop=2160:3840,setsar=1[base_{pad_out}];"
    
    frames = round(duration * fps)
    
    if preset == "zoom_in":
        zp = f"zoompan=z='min(zoom+0.0015,1.5)':d={frames}:s=1080x1920:fps={fps}"
    elif preset == "zoom_out":
        zp = f"zoompan=z='if(lte(zoom,1.0),1.5,max(1.001,zoom-0.0015))':d={frames}:s=1080x1920:fps={fps}"
    elif preset == "pan_left":
        zp = f"zoompan=z=1.2:x='if(eq(in,1),iw*0.2,x-2)':y='(ih-ih/zoom)/2':d={frames}:s=1080x1920:fps={fps}"
    elif preset == "pan_right":
        zp = f"zoompan=z=1.2:x='if(eq(in,1),0,x+2)':y='(ih-ih/zoom)/2':d={frames}:s=1080x1920:fps={fps}"
    elif preset == "pan_up":
        zp = f"zoompan=z=1.2:x='(iw-iw/zoom)/2':y='if(eq(in,1),ih*0.2,y-2)':d={frames}:s=1080x1920:fps={fps}"
    elif preset == "pan_down":
        zp = f"zoompan=z=1.2:x='(iw-iw/zoom)/2':y='if(eq(in,1),0,y+2)':d={frames}:s=1080x1920:fps={fps}"
    elif preset == "zoom_in_pan_left":
        zp = f"zoompan=z='min(zoom+0.0015,1.5)':x='if(eq(in,1),iw*0.2,x-1)':y='(ih-ih/zoom)/2':d={frames}:s=1080x1920:fps={fps}"
    elif preset == "static":
        zp = f"zoompan=z=1.0:d={frames}:s=1080x1920:fps={fps}"

    filter_str = f"{base}[base_{pad_out}]{zp}[{pad_out}]"
    return filter_str, preset
