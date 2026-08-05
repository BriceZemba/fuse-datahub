"""Model access, with an honest no-key path.

FUSE_LLM_PROVIDER=none disables the two LLM nodes; strategy selection falls back to
rules and generation falls back to templates. Output is blunter, the pipeline still
completes, and the repo is never unrunnable for someone without an API key.
"""

from __future__ import annotations

import os
from typing import Any

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# OpenRouter's free tier carries open-weight models at no cost, but the `:free` ids are
# volatile - qwen3-coder:free was delisted in July 2026, Kimi lost its free tag in June.
# So this is a default, not a promise: run `fuse models` to see what is free today and
# set FUSE_LLM_MODEL accordingly.
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4.1",
    "openrouter": "z-ai/glm-4.5-air:free",
    "ollama": os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b"),
}


def llm_available(provider: str | None = None) -> bool:
    provider = (provider or os.getenv("FUSE_LLM_PROVIDER", "none")).lower()
    if provider == "none":
        return False
    if provider == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))
    if provider == "openrouter":
        return bool(os.getenv("OPENROUTER_API_KEY"))
    return provider == "ollama"


def get_llm(provider: str | None = None, *, temperature: float = 0.0) -> Any | None:
    provider = (provider or os.getenv("FUSE_LLM_PROVIDER", "none")).lower()
    if not llm_available(provider):
        return None
    model = os.getenv("FUSE_LLM_MODEL", DEFAULT_MODELS.get(provider, ""))

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model, temperature=temperature, max_tokens=8000)
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model, temperature=temperature)
    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            temperature=temperature,
            base_url=OPENROUTER_BASE_URL,
            api_key=os.environ["OPENROUTER_API_KEY"],
            default_headers={
                "HTTP-Referer": "https://github.com/BriceZemba/fuse-datahub",
                "X-Title": "Fuse",
            },
        )
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=model, temperature=temperature)
    return None
