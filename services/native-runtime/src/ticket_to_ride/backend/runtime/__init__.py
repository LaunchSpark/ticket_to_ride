"""
Expose the managed runtime package surface for the backend API.

This package owns the native managed-match runtime. It provides the match
orchestrator plus the executor/result types that callers need to configure or
test the runtime from outside the package.
"""

from ticket_to_ride.backend.runtime.executor import BotExecutor
from ticket_to_ride.backend.runtime.managed_match_runtime import (
    ManagedMatchNotFoundError,
    ManagedMatchRuntimeManager,
    ManagedRoundNotFoundError,
    ManagedRuntimeError,
)
from ticket_to_ride.backend.runtime.models import ExecutionResult

__all__ = [
    "BotExecutor",
    "ExecutionResult",
    "ManagedMatchNotFoundError",
    "ManagedMatchRuntimeManager",
    "ManagedRoundNotFoundError",
    "ManagedRuntimeError",
]
