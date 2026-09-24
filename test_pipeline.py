import asyncio
import os
import uuid
from shorts.models import JobSpec, GeneratedScript, Scene
from shorts.pipeline import generate

async def main():
    job = JobSpec(topic="Rome", voice_id="en-US-AriaNeural")
    gen = generate(job)
    try:
        async for event in gen:
            print(event)
    except Exception as e:
        print("Error:", e)

asyncio.run(main())
