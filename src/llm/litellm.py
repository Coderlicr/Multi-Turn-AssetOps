"""Unified LLM backend via the litellm library.

Supports any model string that litellm recognizes.  The provider is encoded
in the model-string prefix — no separate platform flag is needed:

    watsonx/meta-llama/llama-3-3-70b-instruct   → IBM WatsonX
    litellm_proxy/GCP/claude-4-sonnet            → LiteLLM proxy
    tokenrouter/z-ai/glm-5.3-flash               → TokenRouter (OpenAI-compatible)

Credentials are resolved from environment variables based on the prefix:

    watsonx/*      :  WATSONX_APIKEY, WATSONX_PROJECT_ID, WATSONX_URL (optional)
    tokenrouter/*  :  TOKENROUTER_API_KEY, TOKENROUTER_BASE_URL
    otherwise      :  LITELLM_API_KEY, LITELLM_BASE_URL

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
from .routers import TOKENROUTER_PREFIX, resolve_model, resolve_router_creds

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


def omits_temperature(model_id: str) -> bool:
    """True for models that reject an explicit temperature.

    OpenAI's gpt-5 family only accepts temperature=1, and litellm raises
    UnsupportedParamsError for anything else rather than clamping. We drop the
    parameter for those models so the API default applies.

    NOTE: this means gpt-5 models do NOT run at temperature=0 like the rest of
    the backends, so their run-to-run variance is higher. Keep that in mind when
    comparing evaluation numbers across backbones.
    """
    return "gpt-5" in resolve_model(model_id)


def resolve_call_kwargs(model_id: str) -> dict:
    """Return the litellm model string and endpoint credentials for *model_id*.

    Split out from :meth:`LiteLLMBackend.generate` so routing can be tested
    without issuing a network call.
    """
    if model_id.startswith("watsonx/"):
        kwargs = {
            "model": model_id,
            "api_key": os.environ["WATSONX_APIKEY"],
            "project_id": os.environ["WATSONX_PROJECT_ID"],
        }
        if url := os.environ.get("WATSONX_URL"):
            kwargs["api_base"] = url
        return kwargs

    if model_id.startswith(TOKENROUTER_PREFIX):
        creds = resolve_router_creds(model_id)
        # TokenRouter speaks the OpenAI protocol. litellm picks that transport
        # from an "openai/" prefix; without it the bare model name has no
        # provider and the call is rejected before it reaches api_base.
        return {
            "model": f"openai/{resolve_model(model_id)}",
            "api_key": creds.api_key,
            "api_base": creds.base_url,
        }

    # litellm_proxy/* keeps its prefix — litellm resolves that provider itself.
    return {
        "model": model_id,
        "api_key": os.environ["LITELLM_API_KEY"],
        "api_base": os.environ["LITELLM_BASE_URL"],
    }


class LiteLLMBackend(LLMBackend):
    """LLM backend using the litellm library.

    Args:
        model_id: litellm model string with provider prefix, e.g.:
                  ``"watsonx/meta-llama/llama-3-3-70b-instruct"``
                  ``"litellm_proxy/GCP/claude-4-sonnet"``
                  ``"tokenrouter/z-ai/glm-5.3-flash"``
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
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
            **resolve_call_kwargs(self._model_id),
        }
        if not omits_temperature(self._model_id):
            kwargs["temperature"] = temperature

        response = litellm.completion(**kwargs)
        return response.choices[0].message.content
