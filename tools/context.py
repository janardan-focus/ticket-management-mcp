"""
ToolContext — per-request context passed into every tool handler.

Kept in its own module to avoid circular imports between registry.py
(which imports from tool modules) and the tool modules themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.client import TMSApiClient


@dataclass
class ToolContext:
    """Per-request context passed into every tool handler."""
    api: TMSApiClient
