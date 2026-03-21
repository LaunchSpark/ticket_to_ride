# Bot Execution Path

The current runtime uses the external HTTP bot API as the only concrete controller execution target.

## Current Path

```text
managed_match_runtime.py
  -> round_runtime.py
  -> executor.py: BotApiExecutor
  -> integrations/external/clients/bot_api/app.py
  -> integrations/external/clients/bot_api/service.py: BotSessionManager
  -> loaded BaseBot subclass
```

## Session Lifecycle

- `BotApiExecutor.start()`
  - `POST /bot-sessions`
  - creates one external bot session for one seat controller runtime
- `BotApiExecutor.invoke()`
  - posts to one decision endpoint for the active method
  - sends player context, remaining round time, initial time, and increment
- `BotApiExecutor.close()`
  - `DELETE /bot-sessions/{sessionId}`
  - tears the external session down at round end

## Normalized Result Contract

`BotApiExecutor` returns `ExecutionResult` with one of these statuses:

- `ok`
- `bot_exception`
- `per_call_timeout`
- `clock_flagged`
- `invalid_response`
- `transport_error`
- `controller_teardown_failed`

That keeps round orchestration independent of HTTP details.

## Extension Point

The executor boundary is intentionally narrow:

- `BotExecutor.start()`
- `BotExecutor.invoke()`
- `BotExecutor.close()`

Future executors such as `InProcessExecutor` or `DockerSandboxExecutor` should implement that interface and return the same normalized `ExecutionResult` shape.
