# Flow: Create Managed Match

## Steps

1. The frontend sends `POST /managed-matches` to `services/native-runtime/src/ticket_to_ride/backend/app.py`.
2. `ManagedMatchRuntimeManager.create_managed_match()` validates the registered bot IDs through the repository and creates a managed-match record.
3. The manager stores a live `MatchExecutionContext` in memory and starts a background thread for that match.
4. The background thread marks the managed match `running` in storage.
5. `replay_transport.build_managed_replay_logger()` creates a repository-backed `GameLogger`.
6. The replay logger starts a replay/log match record through the normal `/matches` persistence path.

## Participating Modules

- `backend/app.py`
- `backend/runtime/managed_match_runtime.py`
- `backend/runtime/replay_transport.py`
- `backend/repository.py`

## Inputs and Outputs

- Input
  - managed match name
  - seat list with primary bot IDs
  - match-wide fallback bot ID
  - round count
  - time control
  - timeout policy
- Output
  - `ManagedMatchSummary`
  - live match thread plus persisted managed-match record
