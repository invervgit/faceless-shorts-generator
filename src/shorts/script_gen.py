import json
import logging
import os
import re
from typing import Any, List, Literal, Optional

import jinja2
from pydantic import BaseModel

from shorts.cache import cache
from shorts.config import ProviderConfig, settings
from shorts.http import fetch

logger = logging.getLogger(__name__)

# --- Models ---
class ScriptScene(BaseModel):
    narration: str
    image_query: str
    subject_type: Literal["person", "place", "object", "concept"]
    subject_name: Optional[str] = None

class GeneratedScript(BaseModel):
    title: str
    hook: str
    scenes: List[ScriptScene]
    cta: str
    hashtags: List[str]

# --- Jinja2 Setup ---
jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(settings.templates_dir),
    autoescape=False,
)

def _extract_json(text: str) -> str:
    """Attempts to extract JSON from markdown code blocks or plain text."""
    text = text.strip()
    # Try to find a JSON code block
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        return match.group(1)
    
    # Try to find anything that looks like a JSON object
    match = re.search(r'(\{.*\})', text, re.DOTALL)
    if match:
        return match.group(1)
        
    return text

# --- Adapters ---
async def call_openai_compatible(
    provider: ProviderConfig,
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
) -> str:
    """Calls an OpenAI-compatible Chat Completions endpoint."""
    api_key = os.getenv(provider.api_key_env)
    if not api_key:
        raise ValueError(f"Missing API key: {provider.api_key_env}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": provider.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.7,
    }
    
    if provider.supports_json_mode:
        payload["response_format"] = {"type": "json_object"}

    response = await fetch(
        method="POST",
        url=provider.base_url,
        json=payload,
        headers=headers,
        use_cache=False, 
    )
    
    data = response.json()
    return data["choices"][0]["message"]["content"]


async def call_gemini(
    provider: ProviderConfig,
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
) -> str:
    """Calls Gemini GenerateContent API natively."""
    api_key = os.getenv(provider.api_key_env)
    if not api_key:
        raise ValueError(f"Missing API key: {provider.api_key_env}")

    # base_url has {model} placeholder
    url = provider.base_url.format(model=provider.model)
    url = f"{url}?key={api_key}"

    headers = {"Content-Type": "application/json"}
    
    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
        }
    }
    
    if provider.supports_json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    response = await fetch(
        method="POST",
        url=url,
        json=payload,
        headers=headers,
        use_cache=False,
    )
    
    data = response.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        logger.error(f"Failed to extract content from Gemini response: {data}")
        raise ValueError(f"Invalid Gemini response format: {e}")


async def generate_script(topic: str, tone: str = "documentary", duration_seconds: int = 30) -> GeneratedScript:
    """
    Generates a script using a cascade of AI providers.
    Enforces word count and pydantic schema.
    """
    target_words = int(duration_seconds * (150 / 60))
    
    try:
        template = jinja_env.get_template(f"{tone}.j2")
    except jinja2.exceptions.TemplateNotFound:
        raise ValueError(f"Tone template '{tone}.j2' not found in {settings.templates_dir}")
        
    schema_json = GeneratedScript.model_json_schema()
    
    system_prompt = (
        "You are an expert short-form video scriptwriter. "
        "Output strictly in JSON matching the requested schema.\n"
        f"Schema: {json.dumps(schema_json)}"
    )
    
    user_prompt = template.render(topic=topic, target_words=target_words, duration=duration_seconds)
    
    # Setup cache key
    cache_key_data = f"{topic}_{tone}_{duration_seconds}"
    
    for provider in settings.providers:
        # Check cache incorporating the provider model
        provider_cache_key = f"{cache_key_data}_{provider.model}"
        cached = cache.get_json("script_gen", provider_cache_key)
        if cached:
            try:
                logger.info(f"Using cached script from {provider.model}")
                return GeneratedScript.model_validate(cached)
            except Exception:
                logger.warning(f"Failed to validate cached script for {provider.model}")
        
        try:
            logger.info(f"Attempting script generation with {provider.name} ({provider.model})")
            
            if provider.is_openai_compatible:
                result_text = await call_openai_compatible(provider, system_prompt, user_prompt, schema_json)
            else:
                result_text = await call_gemini(provider, system_prompt, user_prompt, schema_json)
                
            # Parse and Validate JSON
            clean_json = _extract_json(result_text)
            try:
                script_dict = json.loads(clean_json)
                script = GeneratedScript.model_validate(script_dict)
            except Exception as e:
                logger.warning(f"Failed to parse/validate JSON from {provider.name}: {e}\nResponse: {result_text}")
                continue

            # Word count validation
            words = []
            for scene in script.scenes:
                words.extend(scene.narration.split())
            word_count = len(words)
            
            lower_bound = int(target_words * 0.85)
            upper_bound = int(target_words * 1.15)
            
            if not (lower_bound <= word_count <= upper_bound):
                logger.warning(f"Word count {word_count} out of bounds ({lower_bound}-{upper_bound}). Retrying...")
                # Retry once with a correction message
                correction = (
                    f"Your previous attempt had {word_count} words in the narration. "
                    f"You MUST hit exactly ~{target_words} words total across all scenes."
                )
                
                try:
                    if provider.is_openai_compatible:
                        result_text = await call_openai_compatible(provider, system_prompt, user_prompt + "\n\n" + correction, schema_json)
                    else:
                        result_text = await call_gemini(provider, system_prompt, user_prompt + "\n\n" + correction, schema_json)
                        
                    clean_json = _extract_json(result_text)
                    script_dict = json.loads(clean_json)
                    script = GeneratedScript.model_validate(script_dict)
                except Exception as e:
                    logger.warning(f"Retry failed for {provider.name}: {e}")
                    # If retry fails parsing, we continue to next provider
                    continue
                
                # We do not strictly fail on the second attempt's word count, we accept it as best effort.
            
            # Save to cache
            cache.set_json("script_gen", provider_cache_key, script.model_dump())
            return script
            
        except Exception as e:
            logger.error(f"Provider {provider.name} failed: {e}")
            continue
            
    raise RuntimeError("All providers in the cascade failed to generate a script.")
