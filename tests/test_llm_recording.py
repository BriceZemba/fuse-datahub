"""LLM recordings must belong to the model that made them.

Keying them on the prompt alone made FUSE_LLM_MODEL a no-op: a 9B request was served
120B output from cache, and the run reported 0.0s without calling anything.
"""

from __future__ import annotations

import pytest

from fuse.datahub.cache import CallCache
from fuse.runtime import Runtime


class FakeLLM:
    def __init__(self, model: str, reply: str) -> None:
        self.model = model
        self.reply = reply
        self.calls = 0

    async def ainvoke(self, prompt: str):
        self.calls += 1
        return type("Response", (), {"content": self.reply})()


class FakeDH:
    def __init__(self, cache: CallCache) -> None:
        self.cache = cache


@pytest.fixture
def runtime(tmp_path):
    rt = Runtime()
    rt.dh = FakeDH(CallCache(tmp_path))
    return rt


async def test_a_recording_is_reused_by_the_same_model(runtime):
    runtime.llm = FakeLLM("big-model", "first answer")
    assert await runtime.ask_llm("codegen", "prompt") == "first answer"
    assert await runtime.ask_llm("codegen", "prompt") == "first answer"
    assert runtime.llm.calls == 1


async def test_a_different_model_regenerates(runtime):
    runtime.llm = FakeLLM("big-model", "big answer")
    await runtime.ask_llm("codegen", "prompt")

    runtime.llm = FakeLLM("small-model", "small answer")
    assert await runtime.ask_llm("codegen", "prompt") == "small answer"
    assert runtime.llm.calls == 1
    assert any("regenerating with small-model" in line for line in runtime.log)


async def test_an_unattributed_recording_is_not_trusted_live(runtime, tmp_path):
    """Recordings written before models were tracked must not satisfy any model."""
    runtime.dh.cache.put("llm:codegen", {"prompt": "prompt"}, "legacy answer")
    runtime.llm = FakeLLM("small-model", "fresh answer")
    assert await runtime.ask_llm("codegen", "prompt") == "fresh answer"
    assert runtime.llm.calls == 1


async def test_replay_takes_whatever_was_recorded(runtime):
    runtime.dh.cache.put("llm:codegen", {"prompt": "prompt"}, "legacy answer")
    runtime.llm = None
    assert await runtime.ask_llm("codegen", "prompt") == "legacy answer"


async def test_no_client_and_no_recording_falls_back_to_templates(runtime):
    runtime.llm = None
    assert await runtime.ask_llm("codegen", "prompt") is None


class FailingLLM:
    model = "rate-limited-model"

    async def ainvoke(self, prompt: str):
        raise RuntimeError("Error code: 429 - rate limit exceeded: free-models-per-day")


async def test_a_rate_limit_degrades_instead_of_killing_the_run(runtime):
    """Free tiers run out. Losing the entire analysis to that would be absurd — the
    caller falls back to templates and the trace says what happened."""
    runtime.llm = FailingLLM()
    assert await runtime.ask_llm("codegen", "prompt") is None
    assert runtime.llm_error and "429" in runtime.llm_error
    assert any("falling back to templates" in line for line in runtime.log)


async def test_a_failed_call_is_not_recorded(runtime, tmp_path):
    runtime.llm = FailingLLM()
    await runtime.ask_llm("codegen", "prompt")
    assert not list(tmp_path.glob("llm-codegen*.json")), "a failure must not be cached"
