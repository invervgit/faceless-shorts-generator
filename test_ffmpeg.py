from shorts.render.compose import compose_video
import os

os.makedirs("runs/test", exist_ok=True)
os.makedirs("output", exist_ok=True)

with open("runs/test/scene_0.jpg", "wb") as f:
    pass # Empty file for testing FFmpeg parsing

with open("runs/test/audio.mp3", "wb") as f:
    pass

with open("runs/test/captions.ass", "w") as f:
    f.write("")

try:
    compose_video(
        scene_images=["runs/test/scene_0.jpg"],
        scene_durations=[1.0],
        audio_path="runs/test/audio.mp3",
        output_path="output/test_video.mp4",
        subtitles_path="runs/test/captions.ass",
        job_id="test"
    )
except Exception as e:
    print("Caught:", e)
    
os.system("cat logs/ffmpeg_test.txt")
