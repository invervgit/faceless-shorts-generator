import asyncio
import json
import logging
import os
import random
import subprocess
from datetime import datetime
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv, set_key

# Load environment variables from .env into os.environ
load_dotenv(override=True)

from shorts.captions import ASSGenerator
from shorts.models import WordTiming
from shorts.pipeline import JobSpec, generate
from shorts.tts import list_voices

logger = logging.getLogger(__name__)

SESSION_FILE = Path("config/last_session.json")

def load_session():
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text())
        except Exception:
            pass
    return {}

def save_session(data):
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(data, indent=2))

SURPRISE_TOPICS = [
    "The lost Roman legion in China",
    "Why deep sea creatures are giants",
    "The psychological trick of casino carpets",
    "How the pyramids align with the stars",
    "Why you can't imagine a new color",
    "The secret underground city of Derinkuyu"
]

async def _handle_generate(*args, progress=gr.Progress()):
    keys = [
        "topic", "tone", "duration", "target_scenes",
        "voice_engine", "voice_lang", "voice_id", "voice_rate", "voice_pitch",
        "image_sources", "subject_hint", "motion_style", "transition", "allow_fallback",
        "disable_captions", "caption_style", "font_family", "font_size", "primary_color", "highlight_color", "outline_color", "vertical_pos", "uppercase",
        "intro_path", "outro_path", "logo_path", "logo_pos", "logo_margin", "logo_scale", "logo_opacity",
        "music_path", "music_gain",
        "preset_slider", "crf", "fps", "resolution"
    ]
    state = dict(zip(keys, args))
    
    preset_map = {1: "ultrafast", 2: "veryfast", 3: "fast", 4: "medium", 5: "slow"}
    preset = preset_map.get(int(state["preset_slider"]), "fast")
    
    # Save serializable session
    save_state = {k: (v if not hasattr(v, 'name') else str(Path(v.name).absolute())) for k, v in state.items()}
    save_session(save_state)
    
    job = JobSpec(
        topic=state["topic"], tone=state["tone"], duration=int(state["duration"]), target_scenes=int(state["target_scenes"]),
        voice_engine=state["voice_engine"], voice_lang=state["voice_lang"], voice_id=state["voice_id"], voice_rate=state["voice_rate"], voice_pitch=state["voice_pitch"],
        image_sources=state["image_sources"], subject_hint=state["subject_hint"], motion_style=state["motion_style"], transition=state["transition"], allow_fallback=state["allow_fallback"],
        disable_captions=state["disable_captions"], style=state["caption_style"], font_family=state["font_family"], font_size=int(state["font_size"]), primary_color=state["primary_color"], highlight_color=state["highlight_color"], outline_color=state["outline_color"], vertical_position=int(state["vertical_pos"]), uppercase=state["uppercase"],
        intro_path=save_state.get("intro_path"), outro_path=save_state.get("outro_path"), logo_path=save_state.get("logo_path"), logo_position=state["logo_pos"], logo_margin=int(state["logo_margin"]), logo_scale=float(state["logo_scale"]), logo_opacity=float(state["logo_opacity"]),
        music_path=save_state.get("music_path"), music_gain_db=int(state["music_gain"]),
        render_preset=preset, render_crf=int(state["crf"]), render_fps=int(state["fps"]), render_resolution=state["resolution"],
    )

    final_video = None
    script_json = ""
    manifest_json = ""
    timing_data = ""

    progress(0, desc="Starting pipeline...")
    async for event in generate(job):
        progress(event.pct / 100.0, desc=event.message)
        if event.error:
            raise gr.Error(f"Pipeline failed: {event.error}")
        if event.is_done and event.result_path:
            final_video = event.result_path
            sidecar_path = final_video.replace(".mp4", ".json")
            if os.path.exists(sidecar_path):
                with open(sidecar_path, "r") as f:
                    sidecar = json.load(f)
                    script_json = json.dumps(sidecar.get("job_spec", {}), indent=2)
                    manifest_json = json.dumps(sidecar.get("manifest", []), indent=2)
                    timing_data = json.dumps(sidecar.get("timings", []), indent=2)

    return final_video, final_video, script_json, manifest_json, timing_data

def get_caption_preview(style, font, size, p_color, h_color, o_color, v_pos, upper):
    generator = ASSGenerator()
    words = [WordTiming(word="PREVIEW", start_time=0.0, end_time=1.0), WordTiming(word="TEXT", start_time=1.0, end_time=2.0)]
    ass_content = generator.generate(words, style, font_family=font, font_size=int(size), primary_color=p_color, highlight_color=h_color, outline_color=o_color, vertical_position=int(v_pos), uppercase=upper)
    
    Path("runs").mkdir(exist_ok=True)
    ass_path = Path("runs/preview.ass")
    ass_path.write_text(ass_content, encoding="utf-8")
    img_path = Path("runs/preview.png")
    ass_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=gray:s=1080x1920",
        "-vframes", "1", "-vf", f"subtitles='{ass_escaped}':fontsdir=assets/fonts", str(img_path)
    ]
    subprocess.run(cmd, capture_output=True)
    return str(img_path)

def build_library():
    out_dir = Path("output")
    if not out_dir.exists(): return []
    return [str(mp4) for mp4 in sorted(out_dir.glob("*.mp4"), key=os.path.getmtime, reverse=True)]

with gr.Blocks(theme=gr.themes.Monochrome(text_size="sm")) as app:
    s = load_session()
    
    with gr.Tabs():
        with gr.Tab("Create"):
            with gr.Row():
                with gr.Column(scale=1):
                    with gr.Row():
                        topic = gr.Textbox(label="Topic or Detailed Prompt / Script", value=s.get("topic", ""), lines=4, scale=4, placeholder="Enter a topic or paste a complete script for the AI to follow...")
                        btn_surprise = gr.Button("Surprise Me", scale=1)
                        btn_surprise.click(lambda: random.choice(SURPRISE_TOPICS), outputs=topic)
                        
                    tone = gr.Dropdown(["documentary", "motivational", "listicle", "storytime", "explainer"], label="Tone", value=s.get("tone", "documentary"))
                    duration = gr.Slider(15, 90, value=s.get("duration", 30), step=1, label="Duration (sec)")
                    target_scenes = gr.Slider(2, 10, value=s.get("target_scenes", 5), step=1, label="Number of Photos/Scenes")

                    with gr.Accordion("Voice", open=False):
                        v_engine = gr.Radio(["edge-tts", "kokoro", "piper"], label="Engine", value=s.get("voice_engine", "edge-tts"))
                        v_lang = gr.Dropdown(["en", "es", "fr", "de"], label="Language", value=s.get("voice_lang", "en"))
                        v_id = gr.Dropdown([
                            "en-IN-NeerjaExpressiveNeural", "en-IN-NeerjaNeural", "en-IN-PrabhatNeural",
                            "hi-IN-MadhurNeural", "hi-IN-SwaraNeural",
                            "en-US-ChristopherNeural", "en-US-JennyNeural", "en-GB-SoniaNeural"
                        ], label="Voice ID", value=s.get("voice_id", "hi-IN-MadhurNeural"))
                        v_rate = gr.Textbox(label="Rate", value=s.get("voice_rate", "+0%"))
                        v_pitch = gr.Textbox(label="Pitch", value=s.get("voice_pitch", "+0Hz"))

                    with gr.Accordion("Visuals", open=False):
                        i_sources = gr.CheckboxGroup(["duckduckgo", "wikimedia", "openverse", "pexels", "pixabay", "unsplash", "pollinations"], label="Sources", value=s.get("image_sources", ["duckduckgo", "wikimedia", "openverse", "pexels", "pixabay", "unsplash", "pollinations"]))
                        s_hint = gr.Radio(["auto", "person", "place", "concept"], label="Subject Hint", value=s.get("subject_hint", "auto"))
                        m_style = gr.Dropdown(["auto", "static", "dynamic"], label="Motion Style", value=s.get("motion_style", "auto"))
                        trans = gr.Dropdown(["fade", "slideleft", "dissolve", "wipeup"], label="Transition", value=s.get("transition", "fade"))
                        fallback = gr.Checkbox(label="Allow AI-generated fallback", value=s.get("allow_fallback", True))

                    with gr.Accordion("Captions", open=False):
                        c_disable = gr.Checkbox(label="Disable Captions (Do not render text)", value=s.get("disable_captions", False))
                        c_style = gr.Dropdown(["karaoke", "word", "phrase", "typewriter"], label="Style", value=s.get("caption_style", "karaoke"))
                        c_font = gr.Textbox(label="Font Family", value=s.get("font_family", "Montserrat ExtraBold"))
                        c_size = gr.Slider(10, 80, value=s.get("font_size", 24), step=1, label="Font Size")
                        c_pcol = gr.Textbox(label="Primary Color (ASS)", value=s.get("primary_color", "&H00FFFFFF"))
                        c_hcol = gr.Textbox(label="Highlight Color (ASS)", value=s.get("highlight_color", "&H0000FFFF"))
                        c_ocol = gr.Textbox(label="Outline Color (ASS)", value=s.get("outline_color", "&H00000000"))
                        c_pos = gr.Slider(18, 78, value=s.get("vertical_pos", 78), step=1, label="Vertical Position (%)")
                        c_upper = gr.Checkbox(label="Uppercase", value=s.get("uppercase", True))
                        btn_preview = gr.Button("Preview Caption")
                        c_img = gr.Image(label="Live Preview", type="filepath")
                        btn_preview.click(get_caption_preview, inputs=[c_style, c_font, c_size, c_pcol, c_hcol, c_ocol, c_pos, c_upper], outputs=c_img)

                    with gr.Accordion("Branding", open=False):
                        b_intro = gr.Video(label="Intro Video")
                        b_outro = gr.Video(label="Outro Video")
                        b_logo = gr.Image(label="Logo PNG", type="filepath")
                        b_lpos = gr.Radio(["top_left", "top_center", "top_right", "center", "bottom_left", "bottom_center", "bottom_right"], label="Logo Position", value=s.get("logo_pos", "top_right"))
                        b_lmargin = gr.Slider(0, 200, value=s.get("logo_margin", 40), step=1, label="Logo Margin")
                        b_lscale = gr.Slider(0.05, 0.5, value=s.get("logo_scale", 0.15), step=0.01, label="Logo Scale")
                        b_lopac = gr.Slider(0.0, 1.0, value=s.get("logo_opacity", 1.0), step=0.05, label="Logo Opacity")
                        b_music = gr.Audio(label="Background Music", type="filepath")
                        b_mgain = gr.Slider(-40, 0, value=s.get("music_gain", -18), step=1, label="Music Gain (dB)")

                    with gr.Accordion("Quality", open=False):
                        q_preset = gr.Slider(1, 5, value=s.get("preset_slider", 3), step=1, label="Speed vs Quality (1=fastest, 5=best)")
                        q_crf = gr.Slider(18, 30, value=s.get("crf", 23), step=1, label="CRF")
                        q_fps = gr.Slider(24, 60, value=s.get("fps", 30), step=1, label="FPS")
                        q_res = gr.Dropdown(["1080x1920", "720x1280"], label="Resolution", value=s.get("resolution", "1080x1920"))

                    btn_generate = gr.Button("Generate Short", variant="primary", size="lg")

                with gr.Column(scale=1):
                    out_vid = gr.Video(label="Output Video")
                    out_file = gr.File(label="Download")
                    with gr.Accordion("Debug & Data", open=False):
                        out_script = gr.JSON(label="Script Details")
                        out_manifest = gr.JSON(label="Manifest")
                        out_timing = gr.JSON(label="Timings")

            inputs = [
                topic, tone, duration, target_scenes, v_engine, v_lang, v_id, v_rate, v_pitch,
                i_sources, s_hint, m_style, trans, fallback,
                c_disable, c_style, c_font, c_size, c_pcol, c_hcol, c_ocol, c_pos, c_upper,
                b_intro, b_outro, b_logo, b_lpos, b_lmargin, b_lscale, b_lopac,
                b_music, b_mgain,
                q_preset, q_crf, q_fps, q_res
            ]
            outputs = [out_vid, out_file, out_script, out_manifest, out_timing]
            btn_generate.click(_handle_generate, inputs=inputs, outputs=outputs, concurrency_limit=1)

        with gr.Tab("Library"):
            lib_gallery = gr.Gallery(label="Generated Shorts", value=build_library())
            btn_refresh = gr.Button("Refresh Library")
            btn_refresh.click(build_library, outputs=lib_gallery)

        with gr.Tab("Settings & Health"):
            gr.Markdown("### API Keys")
            for source in ["Pexels", "Pixabay", "Unsplash", "Openverse_Client"]:
                with gr.Row():
                    gr.Textbox(label=f"{source} API Key", type="password", scale=3)
                    gr.Button("Test", scale=1)
            
            gr.Markdown("### Circuit Breaker Health")
            btn_health = gr.Button("Refresh Health")
            health_out = gr.JSON()
            def get_health():
                from shorts.sources import registry
                cur = registry.breaker.conn.execute("SELECT * FROM source_health")
                import time
                return [{"source": r[0], "fails": r[1], "latency": round(r[3], 2), "blocked": bool(r[4] > time.time())} for r in cur.fetchall()]
            btn_health.click(get_health, outputs=health_out)
            
            gr.Markdown("### Cache")
            btn_cache = gr.Button("Calculate Cache Size")
            cache_out = gr.Textbox(label="Result")
            def check_cache():
                from shorts.cache import cache
                size = sum(f.stat().st_size for f in cache.cache_dir.glob('**/*') if f.is_file())
                return f"Total cache size: {size / (1024*1024):.2f} MB"
            btn_cache.click(check_cache, outputs=cache_out)

if __name__ == "__main__":
    app.queue(default_concurrency_limit=1).launch()
