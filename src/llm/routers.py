"""Resolve model identifiers routed through OpenAI-compatible proxies.

The existing Multi-Turn agents use :class:`llm.litellm.LiteLLMBackend`.
Stirrup uses its own clients, so it only needs the endpoint/key resolution
shared here for LiteLLM Proxy and TokenRouter model prefixes.
"""

from __future__ import annotations

import os
from typing import NamedTuple

LITELLM_PREFIX = "litellm_proxy/"
TOKENROUTER_PREFIX = "tokenrouter/"


class RouterCreds(NamedTuple):
    prefix: str
    base_url: str
    api_key: str


PROXY_ROUTERS: dict[str, tuple[str, str]] = {
    LITELLM_PREFIX: ("LITELLM_BASE_URL", "LITELLM_API_KEY"),
    TOKENROUTER_PREFIX: ("TOKENROUTER_BASE_URL", "TOKENROUTER_API_KEY"),
}


def router_prefix(model_id: str) -> str | None:
    """Return the configured proxy prefix in *model_id*, if any."""
    for prefix in PROXY_ROUTERS:
        if model_id.startswith(prefix):
            return prefix
    return None


def resolve_model(model_id: str) -> str:
    """Strip a known routing prefix before sending the model to the endpoint."""
    prefix = router_prefix(model_id)
    return model_id[len(prefix) :] if prefix else model_id


def resolve_router_creds(model_id: str) -> RouterCreds | None:
    """Return endpoint credentials for a proxied model identifier."""
    prefix = router_prefix(model_id)
    if prefix is None:
        return None
    base_env, key_env = PROXY_ROUTERS[prefix]
    base_url = os.environ.get(base_env)
    api_key = os.environ.get(key_env)
    if not base_url or not api_key:
        raise ValueError(
            f"{base_env} and {key_env} must be set when using {prefix!r}"
        )
    return RouterCreds(prefix=prefix, base_url=base_url, api_key=api_key)
