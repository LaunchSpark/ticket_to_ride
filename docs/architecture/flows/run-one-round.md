# Flow: Run One Round

## Steps

1. `ManagedMatchRuntimeManager` creates a managed-round record and starts a replay round through `GameLogger.start_round()`.
2. The manager creates a new `RoundExecutionContext`.
3. `RoundExecutionContext.initialize_primary_controllers()` creates one primary controller per seat through `RoundControllerRegistry`.
4. `RoundExecutionContext` builds fresh `Player` objects and wraps them with `ManagedSeatInterface`.
5. The engine `Game` instance runs in-process.
6. Each engine decision calls into `ManagedSeatInterface`, which forwards to `RoundExecutionContext.execute_action()`.
7. `RoundExecutionContext` asks `RoundClockTracker` for the effective timeout budget and routes the call to the active controller executor.
8. On success, the round continues until the engine ends the game or the round runtime terminates a seat.
9. `RoundExecutionContext` finalizes seat results and `RoundControllerRegistry.teardown()` closes all controller executors.
10. `ManagedMatchRuntimeManager` persists managed round status, clock view, runtime view, and seat results.

## Participating Modules

- `backend/runtime/managed_match_runtime.py`
- `backend/runtime/round_runtime.py`
- `backend/runtime/clock.py`
- `backend/runtime/controllers.py`
- `backend/runtime/executor.py`
- `engine/`
- `logging/game_logger.py`

## Inputs and Outputs

- Input
  - one live `MatchExecutionContext`
  - one replay logger
  - one round number
- Output
  - persisted managed round summary
  - persisted replay round linkage
  - updated aggregate match results
