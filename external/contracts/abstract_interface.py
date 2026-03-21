from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ticket_to_ride.engine.player import Player

class Interface:
    def __init__(self):
        """Base interface used by the gameplay loop to query player actions."""
        self.player: Player

    def set_player(self, player):
        """Provide the Player instance that this interface controls."""
        self.player = player
