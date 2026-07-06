import logging
import random
import csv
from collections import Counter, deque
from pathlib import Path
from typing import List, Union, Deque

logger = logging.getLogger(__name__)


TICKETS_CSV_PATH = Path(__file__).resolve().parents[6] / "operations" / "data" / "Destination_tickets.csv"

# ────────────────────────────────────────────────────────────────────────────────
# TrainCardDeck – with 1-letter abbreviations
# ────────────────────────────────────────────────────────────────────────────────
class TrainCardDeck:
    COLOR_COUNTS = {
        "W": 12,  # White
        "B": 12,  # Black
        "U": 12,  # Blue
        "G": 12,  # Green
        "Y": 12,  # Yellow
        "O": 12,  # Orange
        "R": 12,  # Red
        "P": 12,  # Purple
        "L": 14   # Locomotive (wild)
    }

    def __init__(self, rng: 'random.Random | None' = None):
        """Create and shuffle the deck used during the gameplay loop."""
        self._rng = rng or random.Random()
        self._deck: List[str] = []
        self._discard_pile: List[str] = []
        self._face_up: List[str] = []

        # Build deck using abbreviations
        for abbrev, count in self.COLOR_COUNTS.items():
            self._deck.extend([abbrev] * count)

        self._rng.shuffle(self._deck)
        self._refill_face_up_slot()

        # Mulligan rule enforcement
        while self._too_many_locomotives():
            self._mulligan_face_up()

    def get_face_up(self) -> List[str]:
        """Return a snapshot of the market cards available to players."""
        return self._face_up[:]

    def get_discard_pile(self) -> List[str]:
        """Return the current discard pile."""
        return self._discard_pile[:]

    def deck_composition(self) -> 'Counter[str]':
        """Color counts of the face-down draw pile (contents, not order).

        This is hidden information: expose it only through GlobalPrivateView,
        never to bots.
        """
        return Counter(self._deck)

    def __get_full_deck(self) -> List[str]:
        """Internal helper to expose the deck for testing."""
        return self._deck[:]

    def draw_face_up(self, idx: int) -> str:
        """Draw a visible card from the market."""
        card = self._face_up.pop(idx)
        self._refill_face_up_slot()
        if len(self._face_up) < 5 and len(self._deck) >= 1:
            logger.warning("Unable to refill the face-up market to five cards.")
        return card

    def draw_face_down(self) -> str:
        """Draw a random card from the top of the deck."""
        if not self._deck:
            self._reshuffle_discard()
        if not self._deck:
            raise ValueError("No train cards left to draw!")
        return self._deck.pop()

    def discard(self, cards: Union[str, List[str]]):
        """Place spent cards into the discard pile."""
        if isinstance(cards, str):
            self._discard_pile.append(cards)
        else:
            self._discard_pile.extend(cards)

    def _refill_face_up_slot(self):
        """Maintain five cards in the market, reshuffling as needed.

        If both the draw and discard piles are exhausted the market simply
        stays short — there is nothing left to refill from.
        """
        while len(self._face_up) < 5:
            if not self._deck:
                self._reshuffle_discard()
            if not self._deck:
                break
            self._face_up.append(self._deck.pop())
            if self._too_many_locomotives():
                self._mulligan_face_up()

    def _reshuffle_discard(self):
        """Shuffle the discard pile into the deck, keeping any remaining cards."""
        if not self._discard_pile:
            return
        self._deck.extend(self._discard_pile)
        self._rng.shuffle(self._deck)
        self._discard_pile.clear()

    def _too_many_locomotives(self) -> bool:
        """Return ``True`` if the market violates the mulligan rule."""
        return self._face_up.count("L") >= 3

    def _mulligan_face_up(self):
        """Discard and refresh the market when too many locomotives appear."""
        self._discard_pile.extend(self._face_up)
        self._face_up.clear()
        self._refill_face_up_slot()

    def __len__(self):
        """Return the number of cards remaining in the deck."""
        return len(self._deck)

# ────────────────────────────────────────────────────────────────────────────────
# DestinationTicket – as originally defined
# ────────────────────────────────────────────────────────────────────────────────
class DestinationTicket:
    def __init__(self, city1: str, city2: str, value: int):
        """Representation of a destination ticket objective."""
        self.city1 = city1
        self.city2 = city2
        self.value = value
        self.is_completed = False
        # Set once the ticket can no longer be completed (cities cut off from
        # each other, or cheapest completion costs more trains than remain);
        # its value counts against the score immediately.
        self.is_impossible = False

    def __repr__(self):
        return f"{self.city1} → {self.city2} ({self.value} pts)"

# ────────────────────────────────────────────────────────────────────────────────
# TicketDeck – loads tickets from CSV and manages draws
# ────────────────────────────────────────────────────────────────────────────────
class TicketDeck:
    def __init__(self, csv_path: str | Path = TICKETS_CSV_PATH, rng: 'random.Random | None' = None):
        """Load destination tickets and prepare the draw stack."""
        self._master: List[DestinationTicket] = self._load_tickets_from_csv(csv_path)
        self._stack: Deque[DestinationTicket] = deque(self._master)
        self._rng = rng or random.Random()
        self._shuffle_stack()

    def deal_unique(self, n: int) -> List[DestinationTicket]:
        """Draw ``n`` tickets from the stack without replacement."""
        drawn = []
        while n > 0 and self._stack:
            drawn.append(self._stack.popleft())
            n -= 1
        return drawn

    def return_tickets(self, tickets: List[DestinationTicket]):
        """Return unused tickets to the stack and shuffle them in."""
        self._stack.extend(tickets)
        self._shuffle_stack()

    def _shuffle_stack(self):
        """Randomize the order of tickets remaining in the stack."""
        temp_list = list(self._stack)
        self._rng.shuffle(temp_list)
        self._stack = deque(temp_list)

    def __len__(self):
        """Return the number of tickets remaining to be drawn."""
        return len(self._stack)

    @staticmethod
    def _load_tickets_from_csv(csv_path: str | Path) -> List[DestinationTicket]:
        """Read ticket definitions from disk."""
        tickets = []
        with open(csv_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                city1 = row["city1"]
                city2 = row["city2"]
                value = int(row["value"])
                tickets.append(DestinationTicket(city1, city2, value))
        return tickets
