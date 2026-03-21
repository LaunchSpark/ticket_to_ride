"""Repo-root shim for the integrations external package during local development."""

from __future__ import annotations

from pathlib import Path

_EXTERNAL_PACKAGE = Path(__file__).resolve().parent.parent / "integrations" / "external"
__path__ = [str(_EXTERNAL_PACKAGE)]
