import unittest

from ticket_to_ride.backend.repository import InMemoryMatchRepository
from ticket_to_ride.runtime.cli import seed_match_if_empty


class RuntimeBootstrapTests(unittest.TestCase):
    def test_seed_match_if_empty_creates_a_bootstrap_match(self) -> None:
        repository = InMemoryMatchRepository()

        seeded = seed_match_if_empty(repository, round_limit=1)
        matches = repository.list_matches()

        self.assertTrue(seeded)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["status"], "completed")
        self.assertEqual(len(matches[0]["players"]), 2)

    def test_seed_match_if_empty_does_nothing_when_matches_exist(self) -> None:
        repository = InMemoryMatchRepository()
        repository.create_match(
            "existing-match",
            [],
        )

        seeded = seed_match_if_empty(repository, round_limit=1)

        self.assertFalse(seeded)
        self.assertEqual(len(repository.list_matches()), 1)


if __name__ == "__main__":
    unittest.main()
