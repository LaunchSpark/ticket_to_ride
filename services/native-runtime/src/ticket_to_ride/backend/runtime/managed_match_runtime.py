from __future__ import annotations

"""
Own match-scoped orchestration for managed match series.

This module is responsible for:
- creating and tracking managed matches
- sequencing rounds within a match
- updating aggregate results and terminal match status
- exposing match and round read views to the backend API

This module does not own:
- raw bot HTTP transport
- round-local clock accounting
- replay persistence internals
"""

import os
import threading
from typing import Any, Callable, Dict, List, Literal, Optional

from ticket_to_ride.backend.bot_catalog import BotCatalogError
from ticket_to_ride.backend.bot_directory import BotDirectory
from ticket_to_ride.backend.models import (
    ManagedMatchCreateRequest,
    ManagedMatchSeatConfig,
    ManagedMatchSummary,
    ManagedRoundSummary,
    ManagedSeatAggregateResult,
    ManagedSeatRoundResult,
    RoundClockSeatView,
    RoundClockView,
    RoundRuntimeSeatView,
    RoundRuntimeView,
    TimeControlConfig,
)
from ticket_to_ride.backend.repository import MatchRepository
from ticket_to_ride.backend.runtime.executor import BotApiExecutor, BotExecutor, InProcessBotExecutor
from ticket_to_ride.backend.runtime.models import MatchExecutionContext
from ticket_to_ride.backend.runtime.replay_transport import build_managed_replay_logger
from ticket_to_ride.backend.runtime.round_runtime import RoundExecutionContext
from ticket_to_ride.engine.state.game_context import GameContext


class ManagedRuntimeError(RuntimeError):
    """Raised when the managed runtime cannot fulfill a request."""


class ManagedMatchNotFoundError(KeyError):
    """Raised when a managed match cannot be found."""


class ManagedRoundNotFoundError(KeyError):
    """Raised when a managed round cannot be found."""


class ManagedMatchRuntimeManager:
    """Manage match-scoped managed runtime lifecycles and background execution."""

    def __init__(
        self,
        repository: MatchRepository,
        *,
        executor_factory: Optional[Callable[[str], BotExecutor]] = None,
        bot_directory: Optional[BotDirectory] = None,
    ) -> None:
        self.repository = repository
        self.repository.interrupt_incomplete_managed_matches()
        self.bot_directory = bot_directory or BotDirectory(repository)
        self.executor_factory = executor_factory or self._build_executor
        self._lock = threading.RLock()
        self._matches: Dict[str, MatchExecutionContext] = {}
        self._threads: Dict[str, threading.Thread] = {}

    def _build_executor(self, bot_id: str) -> BotExecutor:
        try:
            bot = self.bot_directory.resolve(bot_id)
        except (KeyError, BotCatalogError):
            bot = None
        if bot is not None and bot.source == "remote" and bot.base_url:
            return BotApiExecutor(bot_id, base_url=bot.base_url)
        return _default_executor_factory(bot_id)

    def create_managed_match(self, request: ManagedMatchCreateRequest) -> ManagedMatchSummary:
        """Persist and start a new managed match in the background."""

        seats = list(request.seats)
        bot_names = self._resolve_bot_names([seat.primaryBotId for seat in seats] + [request.fallbackBotId])
        name = request.name or "-".join(bot_names[seat.primaryBotId] for seat in seats)
        match_id = self.repository.create_managed_match(
            name=name,
            seats=[seat.model_dump() for seat in seats],
            fallback_bot_id=request.fallbackBotId,
            round_count=request.roundCount,
            time_control=request.timeControl.model_dump(),
            timeout_policy=request.timeoutPolicy,
            execution_mode=request.executionMode,
        )
        match_context = MatchExecutionContext(
            match_id=match_id,
            name=name,
            seats=seats,
            fallback_bot_id=request.fallbackBotId,
            round_count=request.roundCount,
            time_control=request.timeControl,
            timeout_policy=request.timeoutPolicy,
            execution_mode=request.executionMode,
            bot_names=bot_names,
        )
        with self._lock:
            self._matches[match_id] = match_context
            thread = threading.Thread(target=self._run_match, args=(match_id,), daemon=True)
            self._threads[match_id] = thread
            thread.start()
        return self.get_managed_match(match_id)

    def get_managed_match(self, match_id: str) -> ManagedMatchSummary:
        """Return the current summary for one managed match."""

        try:
            record = self.repository.get_managed_match_record(match_id)
        except KeyError as exc:
            raise ManagedMatchNotFoundError(match_id) from exc
        with self._lock:
            live_context = self._matches.get(match_id)
            if live_context is not None:
                record["status"] = live_context.status
                record["currentRoundNumber"] = live_context.current_round_number
                record["replayMatchId"] = live_context.replay_match_id
        return _managed_match_summary_from_record(record)

    def list_managed_matches(self) -> List[ManagedMatchSummary]:
        """Return all persisted managed-match summaries."""

        records = self.repository.list_managed_match_records()
        with self._lock:
            for record in records:
                live_context = self._matches.get(record["id"])
                if live_context is None:
                    continue
                record["status"] = live_context.status
                record["currentRoundNumber"] = live_context.current_round_number
                record["replayMatchId"] = live_context.replay_match_id
        return [_managed_match_summary_from_record(record) for record in records]

    def list_rounds(self, match_id: str) -> List[ManagedRoundSummary]:
        """Return all persisted round summaries for one managed match."""

        try:
            records = self.repository.list_managed_round_records(match_id)
        except KeyError as exc:
            raise ManagedMatchNotFoundError(match_id) from exc
        return [_managed_round_summary_from_record(record) for record in records]

    def get_round(self, match_id: str, round_number: int) -> ManagedRoundSummary:
        """Return one persisted round summary."""

        try:
            record = self.repository.get_managed_round_record(match_id, round_number)
        except KeyError as exc:
            raise ManagedRoundNotFoundError(f"{match_id}:{round_number}") from exc
        return _managed_round_summary_from_record(record)

    def get_round_clock(self, match_id: str, round_number: int) -> RoundClockView:
        """Return the live or persisted clock view for one round."""

        with self._lock:
            live_match = self._matches.get(match_id)
            if live_match is not None and live_match.active_round is not None and live_match.active_round.round_number == round_number:
                return live_match.active_round.clock_view()
        try:
            record = self.repository.get_managed_round_record(match_id, round_number)
        except KeyError as exc:
            raise ManagedRoundNotFoundError(f"{match_id}:{round_number}") from exc
        return RoundClockView(
            matchId=match_id,
            roundNumber=round_number,
            status=record["status"],
            seats=[RoundClockSeatView.model_validate(seat) for seat in record.get("clockState", [])],
        )

    def get_round_runtime(self, match_id: str, round_number: int) -> RoundRuntimeView:
        """Return the live or persisted runtime view for one round."""

        with self._lock:
            live_match = self._matches.get(match_id)
            if live_match is not None and live_match.active_round is not None and live_match.active_round.round_number == round_number:
                return live_match.active_round.runtime_view()
        try:
            record = self.repository.get_managed_round_record(match_id, round_number)
        except KeyError as exc:
            raise ManagedRoundNotFoundError(f"{match_id}:{round_number}") from exc
        return RoundRuntimeView(
            matchId=match_id,
            roundNumber=round_number,
            status=record["status"],
            replayRoundId=record.get("replayRoundId"),
            seats=[RoundRuntimeSeatView.model_validate(seat) for seat in record.get("runtimeState", [])],
        )

    def _run_match(self, match_id: str) -> None:
        with self._lock:
            match_context = self._matches[match_id]
            match_context.status = "running"
        self.repository.update_managed_match(match_id, status="running")

        replay_logger = build_managed_replay_logger(self.repository, match_context)
        game_context = GameContext([seat.seatId for seat in match_context.seats])
        replay_match_id = replay_logger.start_match(
            match_context.name,
            map_name=game_context.get_map().map_name,
            seed=game_context.seed,
        )
        match_context.replay_match_id = replay_match_id
        self.repository.update_managed_match(match_id, replayMatchId=replay_match_id)

        final_status: Literal["completed", "failed", "aborted"] = "completed"

        try:
            for round_number in range(match_context.round_count):
                match_context.current_round_number = round_number
                self.repository.update_managed_match(match_id, currentRoundNumber=round_number)

                managed_round_id = self.repository.create_managed_round(match_id, round_number, status="running")
                replay_round_id = replay_logger.start_round(round_number)
                round_context = RoundExecutionContext(
                    match_context=match_context,
                    managed_round_id=managed_round_id,
                    round_number=round_number,
                    replay_round_id=replay_round_id,
                    executor_factory=self.executor_factory,
                )
                with self._lock:
                    match_context.active_round = round_context
                try:
                    round_result = round_context.play_round(replay_logger, game_context)
                finally:
                    with self._lock:
                        match_context.active_round = None

                self._update_aggregate_results(match_id, round_result.seat_results)
                self.repository.update_managed_round(
                    managed_round_id,
                    status=round_context.status,
                    replayRoundId=replay_round_id,
                    seatResults=[result.model_dump() for result in round_result.seat_results],
                    clockState=[seat.model_dump() for seat in round_context.clock_view().seats],
                    runtimeState=[seat.model_dump() for seat in round_context.runtime_view().seats],
                )
                if round_result.abort_match:
                    final_status = "aborted"
                    break
                if round_number + 1 < match_context.round_count:
                    game_context = GameContext([seat.seatId for seat in match_context.seats])
        except Exception:
            final_status = "failed"
        finally:
            if match_context.replay_match_id is not None:
                replay_logger.finalize_match()
            with self._lock:
                match_context.active_round = None
                match_context.status = final_status
            self.repository.update_managed_match(match_id, status=final_status, currentRoundNumber=match_context.current_round_number)

    def _update_aggregate_results(self, match_id: str, seat_results: List[ManagedSeatRoundResult]) -> None:
        record = self.repository.get_managed_match_record(match_id)
        aggregate = {
            entry["seatId"]: dict(entry)
            for entry in record.get("aggregateResults", [])
        }
        for result in seat_results:
            entry = aggregate[result.seatId]
            if result.outcome in {"won", "won_by_forfeit"}:
                entry["roundsWon"] += 1
            if result.outcome in {"lost", "runtime_failure"}:
                entry["roundsLost"] += 1
            if result.outcome == "runtime_failure":
                entry["runtimeFailures"] += 1
        self.repository.update_managed_match(match_id, aggregateResults=list(aggregate.values()))

    def _resolve_bot_names(self, bot_ids: List[str]) -> Dict[str, str]:
        listing = self.bot_directory.list_all()
        by_id = {bot.bot_id: bot for bot in listing.bots}
        resolved: Dict[str, str] = {}
        for bot_id in bot_ids:
            bot = by_id.get(bot_id)
            if bot is None:
                raise ManagedRuntimeError(
                    f"Unknown bot '{bot_id}'. It is not locally discoverable or available on any connection."
                )
            resolved[bot_id] = bot.name
        return resolved


def _managed_match_summary_from_record(record: Dict[str, Any]) -> ManagedMatchSummary:
    return ManagedMatchSummary(
        matchId=record["id"],
        name=record["name"],
        status=record["status"],
        seats=[ManagedMatchSeatConfig.model_validate(seat) for seat in record.get("seats", [])],
        fallbackBotId=record["fallbackBotId"],
        roundCount=record["roundCount"],
        timeControl=TimeControlConfig.model_validate(record["timeControl"]),
        timeoutPolicy=record["timeoutPolicy"],
        executionMode=record["executionMode"],
        replayMatchId=record.get("replayMatchId"),
        currentRoundNumber=record.get("currentRoundNumber"),
        aggregateResults=[ManagedSeatAggregateResult.model_validate(entry) for entry in record.get("aggregateResults", [])],
        createdAt=record.get("createdAt", ""),
    )


def _default_executor_factory(bot_id: str) -> BotExecutor:
    """Use safe local ActionBot execution unless the HTTP sidecar is opted in."""

    enabled = os.getenv("TICKET_TO_RIDE_ENABLE_BOT_API", "").strip().lower()
    if enabled in {"1", "true", "yes", "on"}:
        return BotApiExecutor(bot_id)
    return InProcessBotExecutor(bot_id)


def _managed_round_summary_from_record(record: Dict[str, Any]) -> ManagedRoundSummary:
    return ManagedRoundSummary(
        roundId=record["id"],
        matchId=record["matchId"],
        roundNumber=record["roundNumber"],
        status=record["status"],
        replayRoundId=record.get("replayRoundId"),
        seatResults=[ManagedSeatRoundResult.model_validate(entry) for entry in record.get("seatResults", [])],
        createdAt=record.get("createdAt", ""),
    )
