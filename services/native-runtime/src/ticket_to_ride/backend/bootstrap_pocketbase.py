from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


COLLECTIONS: list[dict[str, Any]] = [
    {
        "name": "bots",
        "type": "base",
        "fields": [
            {"name": "schema_version", "type": "number", "required": True},
            {"name": "bot_id", "type": "text", "required": True},
            {"name": "name", "type": "text", "required": True},
            {"name": "version", "type": "text", "required": True},
            {"name": "description", "type": "text", "required": True},
            {"name": "author", "type": "text", "required": False},
            {"name": "tags", "type": "json", "required": False},
            {"name": "source_kind", "type": "select", "required": True, "values": ["local_api"]},
            {"name": "source_base_url", "type": "text", "required": True},
            {"name": "discovery_path", "type": "text", "required": True},
        ],
    },
    {
        "name": "matches",
        "type": "base",
        "fields": [
            {"name": "name", "type": "text", "required": True},
            {"name": "status", "type": "select", "required": True, "values": ["in_progress", "completed"]},
            {"name": "player_names", "type": "json", "required": False},
            {"name": "players", "type": "json", "required": True},
            {"name": "player_count", "type": "number", "required": False},
            {"name": "averageScores", "type": "json", "required": False},
        ],
    },
    {
        "name": "rounds",
        "type": "base",
        "fields": [
            {"name": "match_id", "type": "text", "required": True},
            {"name": "round_number", "type": "number", "required": True},
            {"name": "turn_count", "type": "number", "required": False},
        ],
    },
    {
        "name": "turns",
        "type": "base",
        "fields": [
            {"name": "match_id", "type": "text", "required": True},
            {"name": "round_id", "type": "text", "required": True},
            {"name": "turn_index", "type": "number", "required": True},
            {"name": "active_player_id", "type": "text", "required": False},
            {"name": "active_player_score", "type": "number", "required": False},
            {"name": "active_player_remaining_trains", "type": "number", "required": False},
            {"name": "active_player_claimed_routes", "type": "json", "required": False},
            {"name": "active_player_destination_tickets", "type": "json", "required": False},
            {"name": "active_player_hand", "type": "json", "required": False},
            {"name": "opponents", "type": "json", "required": False},
            {"name": "market_cards", "type": "json", "required": False},
            {"name": "turn_state", "type": "json", "required": True},
        ],
    },
    {
        "name": "managed_matches",
        "type": "base",
        "fields": [
            {"name": "name", "type": "text", "required": True},
            {
                "name": "status",
                "type": "select",
                "required": True,
                "values": ["queued", "running", "completed", "failed", "aborted", "interrupted"],
            },
            {"name": "seats", "type": "json", "required": True},
            {"name": "fallback_bot_id", "type": "text", "required": True},
            {"name": "round_count", "type": "number", "required": True},
            {"name": "time_control", "type": "json", "required": True},
            {
                "name": "timeout_policy",
                "type": "select",
                "required": True,
                "values": ["loss_on_time", "switch_to_fallback", "abort_match"],
            },
            {"name": "execution_mode", "type": "select", "required": True, "values": ["bot_api"]},
            {"name": "replay_match_id", "type": "text", "required": False},
            {"name": "current_round_number", "type": "number", "required": False},
            {"name": "aggregate_results", "type": "json", "required": False},
        ],
    },
    {
        "name": "managed_rounds",
        "type": "base",
        "fields": [
            {"name": "managed_match_id", "type": "text", "required": True},
            {"name": "round_number", "type": "number", "required": True},
            {
                "name": "status",
                "type": "select",
                "required": True,
                "values": ["queued", "running", "completed", "failed", "aborted", "interrupted"],
            },
            {"name": "replay_round_id", "type": "text", "required": False},
            {"name": "seat_results", "type": "json", "required": False},
            {"name": "clock_state", "type": "json", "required": False},
            {"name": "runtime_state", "type": "json", "required": False},
        ],
    },
]

PROJECT_COLLECTION_NAMES = tuple(collection["name"] for collection in COLLECTIONS)
EXPECTED_FIELD_NAMES = {
    collection["name"]: {field["name"] for field in collection["fields"]}
    for collection in COLLECTIONS
}


class PocketBaseBootstrapError(RuntimeError):
    """Raised when PocketBase schema bootstrap fails."""


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"

    body = None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PocketBaseBootstrapError(f"PocketBase bootstrap request failed ({exc.code}): {detail}") from exc
    except URLError as exc:
        raise PocketBaseBootstrapError(f"PocketBase bootstrap request failed: {exc.reason}") from exc

    if not raw:
        return {}
    return json.loads(raw)


def authenticate_superuser(base_url: str, email: str, password: str) -> str:
    response = _request_json(
        base_url,
        "POST",
        "/api/collections/_superusers/auth-with-password",
        payload={"identity": email, "password": password},
    )
    token = response.get("token")
    if not token:
        raise PocketBaseBootstrapError("PocketBase superuser authentication succeeded without returning a token.")
    return token


def list_collections(base_url: str, token: str) -> list[dict[str, Any]]:
    response = _request_json(base_url, "GET", "/api/collections", token=token, query={"perPage": 200})
    return response.get("items", [])


def collection_field_names(collection: dict[str, Any]) -> set[str]:
    return {
        field["name"]
        for field in collection.get("fields", [])
        if field.get("name") != "id"
    }


def _field_option_values(field: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(field.get("values", []))


def collection_is_valid(existing_collection: dict[str, Any], expected_collection: dict[str, Any]) -> bool:
    actual_fields = {
        field["name"]: field
        for field in existing_collection.get("fields", [])
        if field.get("name") != "id"
    }
    expected_fields = {
        field["name"]: field
        for field in expected_collection.get("fields", [])
    }

    if set(actual_fields) != set(expected_fields):
        return False

    for field_name, expected_field in expected_fields.items():
        actual_field = actual_fields[field_name]
        if actual_field.get("type") != expected_field.get("type"):
            return False
        if bool(actual_field.get("required")) != bool(expected_field.get("required")):
            return False
        if expected_field.get("type") == "select":
            if _field_option_values(actual_field) != tuple(expected_field.get("values", [])):
                return False

    return True


def create_collection(base_url: str, token: str, collection: dict[str, Any]) -> None:
    _request_json(base_url, "POST", "/api/collections", token=token, payload=collection)


def delete_collection(base_url: str, token: str, collection_id: str) -> None:
    _request_json(base_url, "DELETE", f"/api/collections/{collection_id}", token=token)


def validate_project_collections(existing_collections: dict[str, dict[str, Any]]) -> list[str]:
    invalid_collection_names: list[str] = []

    for collection in COLLECTIONS:
        current = existing_collections.get(collection["name"])
        if current is None:
            continue
        if not collection_is_valid(current, collection):
            invalid_collection_names.append(collection["name"])

    return invalid_collection_names


def reset_project_collections(base_url: str, token: str, existing_collections: dict[str, dict[str, Any]]) -> list[str]:
    reset_names: list[str] = []

    for collection_name in ("managed_rounds", "managed_matches", "turns", "rounds", "matches", "bots"):
        current = existing_collections.get(collection_name)
        if current is None:
            continue
        delete_collection(base_url, token, current["id"])
        reset_names.append(collection_name)

    for collection in COLLECTIONS:
        create_collection(base_url, token, collection)
        if collection["name"] not in reset_names:
            reset_names.append(collection["name"])

    return reset_names


def ensure_collections(base_url: str, email: str, password: str) -> str:
    token = authenticate_superuser(base_url, email, password)
    existing_collections = {collection["name"]: collection for collection in list_collections(base_url, token)}

    invalid_collections = validate_project_collections(existing_collections)
    if invalid_collections:
        reset_names = reset_project_collections(base_url, token, existing_collections)
        return f"reset and recreated collections: {', '.join(reset_names)}"

    created_collections: list[str] = []
    for collection in COLLECTIONS:
        current = existing_collections.get(collection["name"])
        if current is not None:
            continue
        create_collection(base_url, token, collection)
        created_collections.append(collection["name"])

    if created_collections:
        return f"created collections: {', '.join(created_collections)}"

    return "collections already valid"


def main() -> None:
    base_url = os.getenv("POCKETBASE_URL", "http://127.0.0.1:8090").rstrip("/")
    admin_email = os.getenv("POCKETBASE_ADMIN_EMAIL")
    admin_password = os.getenv("POCKETBASE_ADMIN_PASSWORD")
    if not admin_email or not admin_password:
        raise SystemExit("Set POCKETBASE_ADMIN_EMAIL and POCKETBASE_ADMIN_PASSWORD before running this bootstrap script.")

    result = ensure_collections(base_url, admin_email, admin_password)
    print(f"PocketBase schema ensured at {base_url}: {result}")


if __name__ == "__main__":
    main()
