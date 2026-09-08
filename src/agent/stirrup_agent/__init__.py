"""Stirrup agent runner subpackage.

Drives Artificial Analysis' Stirrup framework against the Multi-Turn AssetOps
MCP servers, with an optional sandboxed code-execution track.
"""

from .runner import StirrupAgentRunner

__all__ = ["StirrupAgentRunner"]
