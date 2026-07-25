"""Model access, with an honest no-key path.

FUSE_LLM_PROVIDER=none disables the two LLM nodes; strategy selection falls back to
rules and generation falls back to templates. Output is blunter, the pipeline still
completes, and the repo is never unrunnable for someone without an API key.
"""

from __future__ import annotations

import os
from typing import Any

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4.1",
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
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=model, temperature=temperature)
    return None
