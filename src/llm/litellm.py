"""Unified LLM backend via the litellm library.

Supports any model string that litellm recognizes.  The provider is encoded
in the model-string prefix — no separate platform flag is needed:

    watsonx/meta-llama/llama-3-3-70b-instruct   → IBM WatsonX
    litellm_proxy/GCP/claude-4-sonnet            → LiteLLM proxy

Credentials are resolved from environment variables based on the prefix:

    watsonx/*  :  WATSONX_APIKEY, WATSONX_PROJECT_ID, WATSONX_URL (optional)
    otherwise  :  LITELLM_API_KEY, LITELLM_BASE_URL

Profiling hooks (all opt-in via env vars, zero impact when unset):

    LANGCHAIN_API_KEY       → enables LangSmith tracing for every LLM call.
                              Also set LANGCHAIN_PROJECT to choose the project.
                              On the supervisor-specialist branch LangGraph adds
                              graph-level traces on top automatically.

    LITELLM_METRICS_FILE    → path to a JSONL file; one record per LLM call
                              with prompt_tokens, completion_tokens, latency_s.
                              The eval harness sets this per-dialog so WandB
                              can log token/latency metrics after each run.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from .base import LLMBackend

_log = logging.getLogger(__name__)
_callbacks_registered = False


def _register_callbacks() -> None:
    """Register LiteLLM callbacks once, driven entirely by env vars."""
    import litellm

    # ── LangSmith ────────────────────────────────────────────────────────────
    if os.environ.get("LANGCHAIN_API_KEY"):
        callbacks = litellm.success_callback or []
        if "langsmith" not in callbacks:
            litellm.success_callback = callbacks + ["langsmith"]
        _log.info("LiteLLM → LangSmith tracing enabled.")

    # ── Per-call metrics file ─────────────────────────────────────────────────
    metrics_path = os.environ.get("LITELLM_METRICS_FILE")
    if metrics_path:
        try:
            from litellm.integrations.custom_logger import CustomLogger

            class _MetricsFileLogger(CustomLogger):
                """Appends one JSON record per successful LLM call."""

                def log_success_event(self, kwargs, response_obj, start_time, end_time):
                    try:
                        usage = getattr(response_obj, "usage", None)
                        record = {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "model": kwargs.get("model", ""),
                            "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                            "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
                            "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
                            "latency_s": (end_time - start_time).total_seconds(),
                        }
                        with open(metrics_path, "a", encoding="utf-8") as fh:
                            fh.write(json.dumps(record) + "\n")
                    except Exception:
                        pass  # never let logging break an LLM call

            litellm.callbacks = list(litellm.callbacks or []) + [_MetricsFileLogger()]
            _log.info("LiteLLM → metrics file: %s", metrics_path)
        except ImportError:
            _log.warning("litellm.integrations.custom_logger not available; metrics file skipped.")


class LiteLLMBackend(LLMBackend):
    """LLM backend using the litellm library.

    Args:
        model_id: litellm model string with provider prefix, e.g.:
                  ``"watsonx/meta-llama/llama-3-3-70b-instruct"``
                  ``"litellm_proxy/GCP/claude-4-sonnet"``
    """

    def __init__(self, model_id: str) -> None:
        global _callbacks_registered
        self._model_id = model_id
        if not _callbacks_registered:
            _register_callbacks()
            _callbacks_registered = True

    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        import litellm

        kwargs: dict = {
            "model": self._model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": 2048,
        }

        if self._model_id.startswith("watsonx/"):
            kwargs["api_key"] = os.environ["WATSONX_APIKEY"]
            kwargs["project_id"] = os.environ["WATSONX_PROJECT_ID"]
            if url := os.environ.get("WATSONX_URL"):
                kwargs["api_base"] = url
        else:
            kwargs["api_key"] = os.environ["LITELLM_API_KEY"]
            kwargs["api_base"] = os.environ["LITELLM_BASE_URL"]

        response = litellm.completion(**kwargs)
        return response.choices[0].message.content
