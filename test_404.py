import asyncio
import httpx

async def main():
    async with httpx.AsyncClient() as client:
        # test what happens with an invalid model
        resp = await client.request(
            "POST", 
            "https://api.groq.com/openai/v1/chat/completions",
            json={"model": "invalid", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer invalid"}
        )
        print("Groq:", resp.status_code, resp.text)
        
        resp = await client.request(
            "POST", 
            "https://openrouter.ai/api/v1/chat/completions",
            json={"model": "invalid", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer invalid"}
        )
        print("OpenRouter:", resp.status_code, resp.text)

asyncio.run(main())
