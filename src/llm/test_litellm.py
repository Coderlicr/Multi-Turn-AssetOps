import sys
from types import SimpleNamespace

import llm.litellm as backend_module


def test_deepseek_model_uses_deepseek_environment(monkeypatch):
    captured = {}

    def completion(**kwargs):
        captured.update(kwargs)
        message = SimpleNamespace(content="ok")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake_litellm = SimpleNamespace(
        success_callback=[],
        callbacks=[],
        completion=completion,
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.test")
    monkeypatch.delenv("DEEPSEEK_THINKING", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LITELLM_METRICS_FILE", raising=False)
    monkeypatch.setattr(backend_module, "_callbacks_registered", False)

    backend = backend_module.LiteLLMBackend("deepseek/deepseek-chat")
    assert backend.generate("hello") == "ok"
    assert captured["model"] == "deepseek/deepseek-chat"
    assert captured["api_key"] == "test-key"
    assert captured["api_base"] == "https://api.deepseek.test"
    assert captured["max_tokens"] == 8192
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    assert captured["temperature"] == 0.0


def test_generation_token_limit_is_configurable(monkeypatch):
    captured = {}

    def completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(success_callback=[], callbacks=[], completion=completion),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    monkeypatch.setattr(backend_module, "_callbacks_registered", False)
    backend_module.LiteLLMBackend("deepseek/deepseek-chat").generate("hello")
    assert captured["max_tokens"] == 4096


def test_deepseek_thinking_mode_uses_official_openai_parameters(monkeypatch):
    captured = {}

    def completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(success_callback=[], callbacks=[], completion=completion),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_THINKING", "enabled")
    monkeypatch.setenv("DEEPSEEK_REASONING_EFFORT", "low")
    monkeypatch.setattr(backend_module, "_callbacks_registered", False)
    backend_module.LiteLLMBackend("deepseek/deepseek-v4-flash").generate("hello")

    assert captured["extra_body"] == {"thinking": {"type": "enabled"}}
    assert captured["reasoning_effort"] == "low"
    assert "temperature" not in captured
