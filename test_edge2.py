import asyncio
import edge_tts

async def main():
    communicate = edge_tts.Communicate("In 753 BCE, Romulus founded Rome on seven hills.", "en-US-AriaNeural")
    async for chunk in communicate.stream():
        if chunk["type"] == "WordBoundary":
            print(chunk)

asyncio.run(main())
