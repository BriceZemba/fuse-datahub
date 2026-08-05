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

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, prompt: str):
        self.calls += 1
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


class FlakyLLM:
    """Fails with a busy-provider error, then succeeds — what actually happened."""

    model = "flaky-model"

    def __init__(self, failures: int) -> None:
        self.remaining = failures
        self.calls = 0

    async def ainvoke(self, prompt: str):
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise ValueError(
                "{'message': 'Upstream error from Nvidia: ResourceExhausted: Worker "
                "local total request limit reached (33/32)', 'code': 502}"
            )
        return type("Response", (), {"content": "recovered answer"})()


async def test_a_busy_provider_is_retried(runtime, monkeypatch):
    monkeypatch.setattr("fuse.runtime.LLM_BACKOFF_SECONDS", 0)
    runtime.llm = FlakyLLM(failures=1)
    assert await runtime.ask_llm("codegen", "prompt") == "recovered answer"
    assert runtime.llm.calls == 2
    assert runtime.llm_error is None


async def test_retries_give_up_and_fall_back(runtime, monkeypatch):
    monkeypatch.setattr("fuse.runtime.LLM_BACKOFF_SECONDS", 0)
    runtime.llm = FlakyLLM(failures=99)
    assert await runtime.ask_llm("codegen", "prompt") is None
    assert runtime.llm.calls == 3
    assert runtime.llm_error


async def test_a_quota_error_is_not_retried(runtime, monkeypatch):
    """Waiting cannot fix an exhausted daily quota, and retrying burns the clock."""
    monkeypatch.setattr("fuse.runtime.LLM_BACKOFF_SECONDS", 0)
    runtime.llm = FailingLLM()  # 429 free-models-per-day
    assert await runtime.ask_llm("codegen", "prompt") is None
    assert runtime.llm.calls == 1, "a quota failure must not be retried"
