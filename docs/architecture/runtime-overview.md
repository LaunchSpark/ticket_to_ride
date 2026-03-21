# Runtime Overview

The managed runtime is split by scope so each behavior has one clear home.

## Scope Model

- Match scope
  - `MatchExecutionContext`
  - owns seats, primary bot assignments, match-wide fallback bot, round count, aggregate results, and overall status
- Round scope
  - `RoundExecutionContext`
  - owns one full game, controller routing for that game, round clocks, and round-local failover
- Seat scope inside a round
  - `RoundSeatRuntime`
  - owns the active role, primary/fallback controller handles, and elimination/failover status
- Controller scope inside a round
  - `SeatControllerRuntime`
  - owns one live executor-backed controller instance for one seat role

## Ownership by Module

- `managed_match_runtime.py`
  - starts managed matches
  - sequences rounds
  - persists managed round summaries
  - updates aggregate results
- `round_runtime.py`
  - runs one game through the engine
  - routes engine decision points to the active controller
  - finalizes seat results for the round
- `clock.py`
  - tracks `BotClockState`
  - computes effective per-call timeouts
  - applies elapsed-time deductions and turn increments
- `controllers.py`
  - creates primary controllers at round start
  - creates fallback controllers lazily
  - tears all controller executors down at round end
- `failover.py`
  - decides whether a primary failure may switch to fallback
  - records failover reason and active-role change
- `executor.py`
  - owns the actual bot transport path
  - current concrete implementation: `BotApiExecutor`

## Clock Ownership

- The clock belongs to the seat for the current round.
- A new round gets fresh seat clocks.
- Increment is applied after a completed turn through `ManagedSeatInterface.end_turn`.
- If a seat fails over, the fallback controller inherits the same seat clock state.

## Failover Ownership

- Failover is round-scoped, not match-scoped.
- `FailoverCoordinator` may switch a seat from primary to fallback inside the current round.
- The next round starts fresh on the primary bot again.
- The fallback bot choice itself is match-scoped and comes from the managed match config.

## Current Execution Path

The current concrete path is:

```text
RoundExecutionContext
  -> RoundControllerRegistry
  -> BotApiExecutor
  -> external bot API
  -> BotSessionManager
  -> loaded bot class
```

Future executors can plug into the same `BotExecutor` interface without changing match or round orchestration.
