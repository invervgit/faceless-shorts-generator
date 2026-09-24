import sys
import logging
import asyncio
logging.basicConfig(level=logging.INFO)
from shorts.render.compose import compose_video

compose_video(
    scene_images=['runs/382261a0/scene_0.jpeg', 'runs/382261a0/scene_1.jpeg', 'runs/382261a0/scene_2.jpg', 'runs/382261a0/scene_3.jpg'],
    scene_durations=[6.442, 6.442, 5.522, 5.522],
    audio_path='.cache/shorts/90c8fc1017d840630b63fb16aa3b8ff27457e1c836276f3aa0b8ff3b3181a06b.mp3',
    subtitles_path='runs/382261a0/captions.ass',
    output_path='test_final.mp4'
)
