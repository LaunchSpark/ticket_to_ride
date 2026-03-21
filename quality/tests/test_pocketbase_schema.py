from __future__ import annotations

import unittest
from unittest.mock import patch

from ticket_to_ride.backend.bootstrap_pocketbase import (
    COLLECTIONS,
    collection_is_valid,
    ensure_collections,
    reset_project_collections,
    validate_project_collections,
)


class PocketBaseSchemaTests(unittest.TestCase):
    def test_collection_definitions_use_fields_for_ticket_to_ride_schema(self) -> None:
        bots = next(collection for collection in COLLECTIONS if collection["name"] == "bots")
        matches = next(collection for collection in COLLECTIONS if collection["name"] == "matches")
        turns = next(collection for collection in COLLECTIONS if collection["name"] == "turns")

        self.assertIn("fields", bots)
        self.assertNotIn("schema", bots)
        self.assertIn("fields", matches)
        self.assertNotIn("schema", matches)
        self.assertIn("fields", turns)
        self.assertNotIn("schema", turns)

    def test_validate_project_collections_flags_collection_with_only_id_field(self) -> None:
        malformed_collections = {
            "bots": {"id": "bot-col", "name": "bots", "fields": [{"name": "id", "type": "text"}]},
            "matches": {"id": "match-col", "name": "matches", "fields": [{"name": "id", "type": "text"}]},
            "rounds": {"id": "round-col", "name": "rounds", "fields": [{"name": "id", "type": "text"}]},
            "turns": {"id": "turn-col", "name": "turns", "fields": [{"name": "id", "type": "text"}]},
        }

        invalid = validate_project_collections(malformed_collections)

        self.assertEqual(invalid, ["bots", "matches", "rounds", "turns"])

    def test_collection_is_valid_accepts_expected_field_shape(self) -> None:
        expected_turns = next(collection for collection in COLLECTIONS if collection["name"] == "turns")
        existing_turns = {
            "name": "turns",
            "fields": [{"name": "id", "type": "text"}]
            + [dict(field) for field in expected_turns["fields"]],
        }

        self.assertTrue(collection_is_valid(existing_turns, expected_turns))

    def test_reset_project_collections_deletes_and_recreates_only_ticket_to_ride_collections(self) -> None:
        existing = {
            "bots": {"id": "bot-col", "name": "bots", "fields": [{"name": "id", "type": "text"}]},
            "matches": {"id": "match-col", "name": "matches", "fields": [{"name": "id", "type": "text"}]},
            "rounds": {"id": "round-col", "name": "rounds", "fields": [{"name": "id", "type": "text"}]},
            "turns": {"id": "turn-col", "name": "turns", "fields": [{"name": "id", "type": "text"}]},
            "managed_matches": {"id": "managed-match-col", "name": "managed_matches", "fields": [{"name": "id", "type": "text"}]},
            "managed_rounds": {"id": "managed-round-col", "name": "managed_rounds", "fields": [{"name": "id", "type": "text"}]},
            "users": {"id": "users-col", "name": "users", "fields": [{"name": "id", "type": "text"}]},
        }

        with patch("ticket_to_ride.backend.bootstrap_pocketbase.delete_collection") as delete_collection, \
             patch("ticket_to_ride.backend.bootstrap_pocketbase.create_collection") as create_collection:
            reset_names = reset_project_collections("http://127.0.0.1:8090", "token", existing)

        self.assertEqual(reset_names, ["managed_rounds", "managed_matches", "turns", "rounds", "matches", "bots"])
        deleted_ids = [call.args[2] for call in delete_collection.call_args_list]
        self.assertEqual(
            deleted_ids,
            ["managed-round-col", "managed-match-col", "turn-col", "round-col", "match-col", "bot-col"],
        )
        created_names = [call.args[2]["name"] for call in create_collection.call_args_list]
        self.assertEqual(created_names, ["bots", "matches", "rounds", "turns", "managed_matches", "managed_rounds"])

    def test_ensure_collections_repairs_invalid_project_collections(self) -> None:
        invalid_existing = [
            {"id": "bot-col", "name": "bots", "fields": [{"name": "id", "type": "text"}]},
            {"id": "match-col", "name": "matches", "fields": [{"name": "id", "type": "text"}]},
            {"id": "round-col", "name": "rounds", "fields": [{"name": "id", "type": "text"}]},
            {"id": "turn-col", "name": "turns", "fields": [{"name": "id", "type": "text"}]},
            {"id": "users-col", "name": "users", "fields": [{"name": "id", "type": "text"}]},
        ]

        with patch("ticket_to_ride.backend.bootstrap_pocketbase.authenticate_superuser", return_value="token"), \
             patch("ticket_to_ride.backend.bootstrap_pocketbase.list_collections", return_value=invalid_existing), \
             patch("ticket_to_ride.backend.bootstrap_pocketbase.reset_project_collections", return_value=["bots", "matches", "rounds", "turns"]) as reset_project_collections_mock:
            result = ensure_collections("http://127.0.0.1:8090", "admin@example.com", "12345678")

        self.assertIn("reset and recreated collections", result)
        reset_project_collections_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
