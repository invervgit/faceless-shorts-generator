import os
from pathlib import Path
from typing import Optional

import structlog
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", str_strip_whitespace=True)
    
    # LLM Keys
    groq_api_key: Optional[str] = None
    cerebras_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    
    # Image Keys
    pexels_api_key: Optional[str] = None
    pixabay_api_key: Optional[str] = None
    unsplash_access_key: Optional[str] = None
    openverse_client_id: Optional[str] = None
    openverse_client_secret: Optional[str] = None

    cache_dir: Path = Path(".cache/shorts")
    full_user_agent: str = "ShortsGen/1.0 (+contact-email)"
    templates_dir: str = "./config/prompts"
    providers: list = []

    def load_yaml(self, path: str = "config/settings.yaml"):
        import yaml
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    self.templates_dir = data.get("templates_dir", self.templates_dir)
                    # We need to parse into ProviderConfig
                    provs = data.get("providers", [])
                    self.providers = [ProviderConfig(**p) for p in provs]

class ProviderConfig(BaseModel):
    name: str
    base_url: str
    api_key_env: str
    model: str
    is_openai_compatible: bool = True
    supports_json_mode: bool = True

settings = Settings()
settings.load_yaml()

def configure_logging():
    import logging
    
    Path("logs").mkdir(exist_ok=True)
    
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(),
        ],
    )
    
    json_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    file_handler = logging.FileHandler("logs/app.json.log")
    file_handler.setFormatter(json_formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


def startup_check():
    logger = structlog.get_logger(__name__)
    active = []
    skipped = []
    
    if settings.groq_api_key: active.append("Groq")
    else: skipped.append("Groq")
    if settings.cerebras_api_key: active.append("Cerebras")
    else: skipped.append("Cerebras")
    if settings.gemini_api_key: active.append("Gemini")
    else: skipped.append("Gemini")
    if settings.openrouter_api_key: active.append("OpenRouter")
    else: skipped.append("OpenRouter")
    
    if settings.pexels_api_key: active.append("Pexels")
    else: skipped.append("Pexels")
    if settings.pixabay_api_key: active.append("Pixabay")
    else: skipped.append("Pixabay")
    if settings.unsplash_access_key: active.append("Unsplash")
    else: skipped.append("Unsplash")
    if settings.openverse_client_id: active.append("Openverse (OAuth)")
    else: skipped.append("Openverse (OAuth)")
    
    # Base keyless active sources
    active.extend(["Wikimedia", "Openverse (Anon)", "Pollinations", "Edge-TTS"])
    
    logger.info("Startup Check Complete", active_sources=active, missing_keys=skipped)

configure_logging()
startup_check()
