from __future__ import annotations

"""
Own round-scoped orchestration for one full game.

This module is responsible for:
- driving the engine through one round
- creating round-local controller and clock state
- requesting decisions from the active controller
- finalizing round results and tearing down controller state

This module does not own:
- match sequencing
- replay persistence internals
- executor transport details
"""

import threading
from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

from external.contracts.abstract_interface import Interface
from ticket_to_ride.backend.models import ManagedSeatRoundResult, RoundClockView, RoundRuntimeView
from ticket_to_ride.backend.runtime.clock import RoundClockTracker
from ticket_to_ride.backend.runtime.controllers import RoundControllerRegistry
from ticket_to_ride.backend.runtime.failover import FailoverCoordinator
from ticket_to_ride.backend.runtime.models import MatchExecutionContext, RoundStatus, RoundTerminationError
from ticket_to_ride.engine.game import Game
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext

if TYPE_CHECKING:
    from ticket_to_ride.backend.runtime.executor import BotExecutor
    from ticket_to_ride.logging.game_logger import GameLogger

DEFAULT_PLAYER_COLORS = ["red", "blue", "green", "yellow", "black"]


@dataclass
class RoundRunResult:
    """Finalized result of running one managed round."""

    seat_results: list[ManagedSeatRoundResult]
    abort_match: bool


class ManagedSeatInterface(Interface):
    """Engine-facing interface that routes bot decisions through the round runtime."""

    def __init__(self, round_context: "RoundExecutionContext", seat_id: str) -> None:
        super().__init__()
        self.round_context = round_context
        self.seat_id = seat_id
        self._turn_depth = 0

    def begin_turn(self) -> None:
        """Mark the start of an engine turn for increment accounting."""

        self._turn_depth += 1

    def end_turn(self, completed: bool) -> None:
        """Apply increment once a full valid turn completes."""

        if self._turn_depth == 0:
            return
        self._turn_depth -= 1
        if self._turn_depth == 0 and completed:
            self.round_context.complete_turn(self.seat_id)

    def choose_turn_action(self):
        return self.round_context.execute_action(self.seat_id, "choose_turn_action", self.player)

    def choose_draw_train_action(self) -> int:
        return self.round_context.execute_action(self.seat_id, "choose_draw_train_action", self.player)

    def choose_route_to_claim(self, claimable_routes):
        return self.round_context.execute_action(self.seat_id, "choose_route_to_claim", self.player, claimable_routes)

    def choose_color_to_spend(self, route, color_options):
        return self.round_context.execute_action(self.seat_id, "choose_color_to_spend", self.player, route, color_options)

    def select_ticket_offer(self, offer):
        return self.round_context.execute_action(self.seat_id, "select_ticket_offer", self.player, offer)


class RoundExecutionContext:
    """Own one full managed round, including clocks, controllers, and engine flow."""

    def __init__(
        self,
        *,
        match_context: MatchExecutionContext,
        managed_round_id: str,
        round_number: int,
        replay_round_id: str,
        executor_factory: Callable[[str], "BotExecutor"],
    ) -> None:
        self.match_context = match_context
        self.managed_round_id = managed_round_id
        self.round_number = round_number
        self.replay_round_id = replay_round_id
        self.status: RoundStatus = "running"
        self.lock = threading.RLock()
        self.controllers = RoundControllerRegistry.for_round(
            seats=match_context.seats,
            fallback_bot_id=match_context.fallback_bot_id,
            timeout_policy=match_context.timeout_policy,
            executor_factory=executor_factory,
        )
        self.clocks = RoundClockTracker(
            seat_ids=[seat.seatId for seat in match_context.seats],
            time_control=match_context.time_control,
        )
        self.failover = FailoverCoordinator()

    def initialize_primary_controllers(self) -> None:
        """Create all primary controllers for the round."""

        self.controllers.initialize_primary_controllers()

    def play_round(self, replay_logger: "GameLogger", game_context: GameContext) -> RoundRunResult:
        """Run the round to completion and return finalized seat results."""

        self.initialize_primary_controllers()
        players = self._build_round_players()
        replay_logger.set_player_list(players)
        game = Game(game_context, players, replay_logger, self.round_number)
        try:
            game.play()
        except RoundTerminationError as exc:
            seat_results = self._finalize_failed_round(players, exc)
            return RoundRunResult(seat_results=seat_results, abort_match=exc.abort_match)
        finally:
            self.controllers.teardown()
        seat_results = self._finalize_successful_round(players, game)
        return RoundRunResult(seat_results=seat_results, abort_match=False)

    def complete_turn(self, seat_id: str) -> None:
        """Apply the per-turn increment for a completed player turn."""

        with self.lock:
            self.clocks.apply_turn_increment(seat_id)

    def execute_action(self, seat_id: str, action_name: str, player: Player, *args: Any) -> Any:
        """Route one engine decision to the active controller for the seat."""

        with self.lock:
            seat = self.controllers.seat(seat_id)
            clock = self.clocks.clock(seat_id)
            if clock.is_flagged:
                raise self._terminate_for_seat(seat, "clock_flagged", clock.flag_reason or "Seat clock is exhausted.")
        return self._execute_action_internal(seat_id, action_name, player, args, allow_failover=True)

    def clock_view(self) -> RoundClockView:
        """Build the public clock view for the current round."""

        with self.lock:
            return self.clocks.build_clock_view(
                match_id=self.match_context.match_id,
                round_number=self.round_number,
                status=self.status,
                active_roles=self.controllers.active_roles(),
            )

    def runtime_view(self) -> RoundRuntimeView:
        """Build the public runtime view for the current round."""

        with self.lock:
            return self.controllers.build_runtime_view(
                match_id=self.match_context.match_id,
                round_number=self.round_number,
                status=self.status,
                replay_round_id=self.replay_round_id,
            )

    def _build_round_players(self) -> list[Player]:
        players: list[Player] = []
        for index, seat in enumerate(self.match_context.seats):
            interface = ManagedSeatInterface(self, seat.seatId)
            players.append(
                Player(
                    seat.seatId,
                    interface,
                    self._player_display_name(seat.primaryBotId, seat.seatId),
                    _player_color(index),
                )
            )
        return players

    def _player_display_name(self, bot_id: str, seat_id: str) -> str:
        return f"{self.match_context.bot_names[bot_id]} [{seat_id}]"

    def _execute_action_internal(
        self,
        seat_id: str,
        action_name: str,
        player: Player,
        args: tuple[Any, ...],
        *,
        allow_failover: bool,
    ) -> Any:
        with self.lock:
            seat = self.controllers.seat(seat_id)
            clock = self.clocks.clock(seat_id)
            controller = self.controllers.ensure_controller(seat, seat.active_role)
            effective_timeout_ms = self.clocks.effective_timeout_ms(seat_id)
            if clock.remaining_time_ms <= 0:
                self.clocks.flag_clock(seat_id, "Seat clock exhausted.")
                raise self._terminate_for_seat(seat, "clock_flagged", "Seat clock exhausted.")

        controller.state = "running"
        result = controller.executor.invoke(
            action_name,
            player=player,
            timeout_ms=effective_timeout_ms,
            remaining_time_ms=clock.remaining_time_ms,
            initial_time_ms=clock.initial_time_ms,
            increment_ms=self.match_context.time_control.incrementMs,
            args=args,
        )

        retry_on_fallback = False
        with self.lock:
            self.clocks.deduct_elapsed(seat_id, result.elapsed_ms)
            updated_clock = self.clocks.clock(seat_id)
            failure_due_to_clock = updated_clock.is_flagged
            if result.status == "ok" and not failure_due_to_clock:
                self.controllers.mark_ready(controller)
                return result.payload

            failure_status = "clock_flagged" if failure_due_to_clock else result.status
            failure_detail = updated_clock.flag_reason or result.detail or "Controller failed to produce a valid response."
            self.controllers.mark_failed(controller, failure_status, failure_detail)

            retry_on_fallback = allow_failover and self.failover.maybe_activate_fallback(
                seat,
                failure_status=failure_status,
                reason=failure_detail,
                controllers=self.controllers,
            )
            if not retry_on_fallback:
                raise self._terminate_for_seat(
                    seat,
                    failure_status,
                    failure_detail,
                    abort_match=(seat.timeout_policy == "abort_match"),
                    runtime_failure=(failure_status != "clock_flagged"),
                )

        return self._execute_action_internal(seat_id, action_name, player, args, allow_failover=False)

    def _finalize_successful_round(self, players: list[Player], game: Game) -> list[ManagedSeatRoundResult]:
        scores = {player.player_id: game.context.get_score(player.player_id) for player in players}
        winning_score = max(scores.values()) if scores else 0
        seat_results: list[ManagedSeatRoundResult] = []
        with self.lock:
            self.status = "completed"
            for player in players:
                seat = self.controllers.seat(player.player_id)
                clock = self.clocks.clock(player.player_id)
                seat.status = "completed"
                active_bot_id = seat.fallback_bot_id if seat.active_role == "fallback" else seat.primary_bot_id
                outcome = "won" if scores[player.player_id] == winning_score else "lost"
                seat_results.append(
                    ManagedSeatRoundResult(
                        seatId=seat.seat_id,
                        primaryBotId=seat.primary_bot_id,
                        activeBotId=active_bot_id,
                        outcome=outcome,
                        finalScore=scores[player.player_id],
                        remainingTimeMs=clock.remaining_time_ms,
                        activeRole=seat.active_role,
                        hasFailedOver=seat.has_failed_over,
                        failoverReason=seat.failover_reason,
                    )
                )
        return seat_results

    def _finalize_failed_round(self, players: list[Player], failure: RoundTerminationError) -> list[ManagedSeatRoundResult]:
        with self.lock:
            self.status = "aborted" if failure.abort_match else "failed"
            seat_results: list[ManagedSeatRoundResult] = []
            for player in players:
                seat = self.controllers.seat(player.player_id)
                clock = self.clocks.clock(player.player_id)
                active_bot_id = seat.fallback_bot_id if seat.active_role == "fallback" else seat.primary_bot_id
                if seat.seat_id == failure.seat_id:
                    outcome = "aborted" if failure.abort_match else "runtime_failure"
                    seat.status = "eliminated"
                else:
                    outcome = "aborted" if failure.abort_match else "won_by_forfeit"
                    if seat.status != "eliminated":
                        seat.status = "completed"
                seat_results.append(
                    ManagedSeatRoundResult(
                        seatId=seat.seat_id,
                        primaryBotId=seat.primary_bot_id,
                        activeBotId=active_bot_id,
                        outcome=outcome,
                        finalScore=None,
                        remainingTimeMs=clock.remaining_time_ms,
                        activeRole=seat.active_role,
                        hasFailedOver=seat.has_failed_over,
                        failoverReason=seat.failover_reason if seat.has_failed_over or seat.seat_id == failure.seat_id else None,
                    )
                )
        return seat_results

    def _terminate_for_seat(
        self,
        seat,
        status,
        detail: str,
        *,
        abort_match: bool = False,
        runtime_failure: bool = False,
    ) -> RoundTerminationError:
        seat.status = "eliminated"
        if status == "clock_flagged":
            self.clocks.flag_clock(seat.seat_id, detail)
        return RoundTerminationError(
            seat.seat_id,
            detail,
            abort_match=abort_match,
            runtime_failure=runtime_failure,
        )


def _player_color(index: int) -> str:
    return DEFAULT_PLAYER_COLORS[index % len(DEFAULT_PLAYER_COLORS)]
