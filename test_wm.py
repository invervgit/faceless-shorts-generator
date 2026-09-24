import asyncio
import httpx

async def main():
    async with httpx.AsyncClient(http2=False, headers={"User-Agent": "ShortsGen/1.0 (+contact-email)"}) as client:
        resp = await client.get("https://upload.wikimedia.org/wikipedia/commons/0/0f/Statue-Augustus_white_background.jpg")
        print(resp.status_code)

asyncio.run(main())
