import os
import pytest
import subprocess
from unittest.mock import patch

from shorts.models import WordTiming
from shorts.captions import ASSGenerator
from shorts.render.kenburns import get_kenburns_filter
from shorts.render.compose import compose_video

def test_caption_timing_math():
    generator = ASSGenerator(width=1080, height=1920)
    words = [
        WordTiming(word="Hello", start_time=0.0, end_time=0.5),
        WordTiming(word="World", start_time=0.5, end_time=1.2)
    ]
    
    ass = generator.generate(words, style_name="karaoke")
    
    # Hello: 0.5 - 0.0 = 50 centiseconds
    # World: 1.2 - 0.5 = 70 centiseconds
    assert "{\\k50}HELLO" in ass
    assert "{\\k70}WORLD" in ass
    assert "[Script Info]" in ass

def test_ffmpeg_graph_builder(tmp_path):
    # Setup dummy environment to trick os.path.exists checks
    dummy_img = tmp_path / "a.jpg"
    dummy_aud = tmp_path / "audio.mp3"
    dummy_ass = tmp_path / "subs.ass"
    dummy_intro = tmp_path / "intro.mp4"
    dummy_out = tmp_path / "out.mp4"
    
    for f in [dummy_img, dummy_aud, dummy_ass, dummy_intro]:
        f.write_text("fake")
        
    class MockProcess:
        returncode = 0
        stderr = []
        def wait(self): pass
        
    orig_popen = subprocess.Popen
    subprocess.Popen = lambda *a, **k: MockProcess()
    
    try:
        with patch('shorts.render.compose._get_media_info', return_value={'format': {'duration': 5.0}, 'streams': [{'codec_type': 'audio'}]}):
            compose_video(
                scene_images=[str(dummy_img)],
                scene_durations=[5.0],
                audio_path=str(dummy_aud),
                output_path=str(dummy_out),
                subtitles_path=str(dummy_ass),
                job_id="test_job",
                intro_path=str(dummy_intro)
            )
            
        assert os.path.exists("logs/ffmpeg_test_job.txt")
        content = open("logs/ffmpeg_test_job.txt").read()
        
        # Verify graph mechanics
        assert "filter_complex" in content
        assert "xfade" not in content  # Because there is only 1 scene
        assert "subtitles=" in content
        assert "adelay=" in content  # Intro triggers main audio delay
    finally:
        subprocess.Popen = orig_popen

@pytest.mark.smoke
def test_end_to_end():
    # Placeholder for full integration test boundary
    pass
