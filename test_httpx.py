import asyncio
import httpx

async def main():
    async with httpx.AsyncClient() as client:
        url = "https://openrouter.ai/api/v1/chat/completions"
        print(f"POST {url}")
        resp = await client.post(url, json={"model":"meta-llama/llama-3-8b-instruct:free", "messages":[]}, headers={"Authorization": "Bearer test"})
        print(resp.status_code)
        print(resp.text)
        
        url = "https://api.groq.com/openai/v1/chat/completions"
        print(f"POST {url}")
        resp = await client.post(url, json={"model":"llama-3.3-70b-versatile", "messages":[]}, headers={"Authorization": "Bearer test"})
        print(resp.status_code)
        print(resp.text)

asyncio.run(main())
