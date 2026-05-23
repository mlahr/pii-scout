from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Model configuration
    # Options: spacy-fast, spacy-accurate, piiranha, ollama, openrouter
    # Comma-separated for multi-model: "spacy-fast,piiranha"
    model_profile: str = "spacy-fast"
    use_gpu: bool = True

    # Ollama configuration
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # OpenRouter configuration
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str | None = None

    # Piiranha configuration
    piiranha_model_path: str | None = None  # HuggingFace ID or local path

    # API configuration
    max_text_length: int = 500000

    # Server configuration
    host: str = "0.0.0.0"
    port: int = 8000

    # Logging
    log_level: str = "INFO"

    # API metadata
    api_version: str = "1.0.0"

    model_config = {
        "env_prefix": "PII_",
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore",
    }


settings = Settings()
