# Flow: Timeout and Failover

## Steps

1. `RoundExecutionContext.execute_action()` selects the active seat controller and computes the effective timeout from `RoundClockTracker`.
2. The executor invokes the bot and returns `ExecutionResult`.
3. `RoundClockTracker` deducts the elapsed time from the seat clock.
4. If the controller succeeded and the seat clock is still live, the result goes back to the engine.
5. If the controller failed, `RoundControllerRegistry` marks the controller failed or timed out.
6. `FailoverCoordinator` decides whether the failure may switch the seat from primary to fallback.
7. If failover is allowed:
   - the seat is marked failed over
   - the fallback controller is created lazily if needed
   - the same pending decision is retried on the fallback controller
8. If failover is not allowed, `RoundExecutionContext` raises `RoundTerminationError`.
9. The managed match runtime persists the failed round result and either continues to the next round or aborts the match, depending on policy.
10. The next round starts from fresh primaries with fresh clocks.

## Participating Modules

- `backend/runtime/round_runtime.py`
- `backend/runtime/clock.py`
- `backend/runtime/controllers.py`
- `backend/runtime/failover.py`
- `backend/runtime/executor.py`

## Inputs and Outputs

- Input
  - seat ID
  - controller result
  - remaining round time
  - timeout policy
- Output
  - successful fallback retry, or
  - `RoundTerminationError`, or
  - round-local clock flag
