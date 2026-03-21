"""Repo-root shim for the src-based native package during local development."""

from __future__ import annotations

from pathlib import Path

_SRC_PACKAGE = Path(__file__).resolve().parent.parent / "src" / "ticket_to_ride"
__path__ = [str(_SRC_PACKAGE)]

