# Bots Panel Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The viewer's Bots panel auto-discovers all local bots live, the **+** button offers "New Bot" (scaffold a notebook from a name) or "Add Connection" (URL to someone else's bot API), and remote bots are playable in managed matches.

**Architecture:** Bots stop being persisted records. `GET /bots` returns a live merged view: fresh `BotLoader` discovery for local bots plus concurrent pings of persisted **bot connections** (new PocketBase collection, the only persisted entity). A new `BotDirectory` class is the single resolver used by the API endpoints and the managed-match runtime; remote bots route through the existing `BotApiExecutor` with the connection's base URL. The old `bots` collection, `BotSummary`, and register-by-ID flow are removed.

**Tech Stack:** Python 3.12+ / FastAPI / stdlib `urllib` (no `requests`), PocketBase storage, marimo bot notebooks, React-without-JSX viewer (`h()` calls via `components/runtime.jsx`).

**Spec:** `docs/superpowers/specs/2026-07-19-bots-panel-rework-design.md`

## Global Constraints

- Run tests from the repo root: `uv run --with pytest pytest quality/tests/<file>.py -q`. The venv must have extras (`uv sync --all-extras` if imports like `marimo` fail).
- All JSON API fields are camelCase (`botId`, `connectionId`, `baseUrl`, `createdAt`).
- HTTP calls in backend code use stdlib `urllib.request` only — never add `requests`.
- Remote catalog fetches use a 3-second timeout and must be fetched concurrently.
- The loopback-only restriction stays on the legacy env-configured sidecar path (`BOT_API_BASE_URL` + `TICKET_TO_RIDE_ENABLE_BOT_API`) and does NOT apply to user-added connections.
- Viewer components use `h()` from `../runtime.jsx` (exports: `Fragment, RUN_TRANSITION, h, useDeferredValue, useEffect, useMemo, useRef, useState`) — no JSX syntax.
- Commit after every task with a conventional-commit message ending in `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Repo path shorthands below: `BACKEND = services/native-runtime/src/ticket_to_ride/backend`, `VIEWER = applications/viewer`.

---

### Task 1: Allow non-loopback catalog URLs behind an explicit flag

`LocalApiBotCatalogClient` (`BACKEND/bot_catalog.py`) currently rejects any non-loopback base URL. Connections need the same client without that check.

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/backend/bot_catalog.py`
- Test: `quality/tests/test_bot_catalog_remote.py` (new)

**Interfaces:**
- Produces: `LocalApiBotCatalogClient(base_url, *, discovery_path="/bots", timeout_seconds=5, require_loopback=True)` — when `require_loopback=False`, non-loopback http/https hosts are accepted. Everything else (parsing, `source_kind="local_api"`) is unchanged.

- [ ] **Step 1: Write the failing test**

Create `quality/tests/test_bot_catalog_remote.py`:

```python
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from ticket_to_ride.backend.bot_catalog import BotCatalogError, LocalApiBotCatalogClient


def _fake_response(payload):
    class FakeResponse:
        def read(self):
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return FakeResponse()


REMOTE_BOT_PAYLOAD = [
    {
        "schemaVersion": 1,
        "botId": "friend_bot",
        "name": "Friend Bot",
        "version": "2.0.0",
        "description": "A bot served from another machine.",
        "author": "Friend",
        "tags": ["remote"],
    }
]


class RemoteCatalogClientTests(unittest.TestCase):
    def test_non_loopback_base_url_is_rejected_by_default(self) -> None:
        client = LocalApiBotCatalogClient("http://friend-host:8001")

        with self.assertRaises(BotCatalogError):
            client.list_bots()

    def test_non_loopback_base_url_is_allowed_when_loopback_is_not_required(self) -> None:
        client = LocalApiBotCatalogClient("http://friend-host:8001", require_loopback=False)

        with patch(
            "ticket_to_ride.backend.bot_catalog.urlopen",
            return_value=_fake_response(REMOTE_BOT_PAYLOAD),
        ):
            records = client.list_bots()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].bot_id, "friend_bot")
        self.assertEqual(records[0].source_base_url, "http://friend-host:8001")

    def test_non_http_scheme_is_rejected_even_without_loopback_requirement(self) -> None:
        client = LocalApiBotCatalogClient("ftp://friend-host:8001", require_loopback=False)

        with self.assertRaises(BotCatalogError):
            client.list_bots()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --with pytest pytest quality/tests/test_bot_catalog_remote.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'require_loopback'` (2 tests error, the default-rejection test passes).

- [ ] **Step 3: Implement the flag**

In `BACKEND/bot_catalog.py`, change `LocalApiBotCatalogClient.__init__` and `_ensure_local_base_url`:

```python
    def __init__(
        self,
        base_url: str | None = None,
        *,
        discovery_path: str = LOCAL_API_DISCOVERY_PATH,
        timeout_seconds: int = 5,
        require_loopback: bool = True,
    ) -> None:
        self.base_url = (base_url or os.getenv("BOT_API_BASE_URL", DEFAULT_BOT_API_BASE_URL)).rstrip("/")
        self.discovery_path = discovery_path if discovery_path.startswith("/") else f"/{discovery_path}"
        self.timeout_seconds = timeout_seconds
        self.require_loopback = require_loopback
```

```python
    def _ensure_local_base_url(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"}:
            raise BotCatalogError("Configured BOT_API_BASE_URL must use http or https.")
        if self.require_loopback and not _is_loopback_host(parsed.hostname):
            raise BotCatalogError("Configured BOT_API_BASE_URL must point to a local loopback host in v1.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest quality/tests/test_bot_catalog_remote.py quality/tests/test_bot_registry_api.py -q`
Expected: all PASS (the legacy loopback test in `test_bot_registry_api.py` still passes because the default is unchanged).

- [ ] **Step 5: Commit**

```bash
git add quality/tests/test_bot_catalog_remote.py services/native-runtime/src/ticket_to_ride/backend/bot_catalog.py
git commit -m "feat: allow non-loopback bot catalog URLs behind require_loopback flag"
```

---

### Task 2: Bot-connection storage in the repository (ABC + in-memory)

Add connection persistence methods. Do NOT remove the old bot methods yet — the runtime still uses them until Task 7; removal happens in Task 8.

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/backend/repository.py`
- Test: `quality/tests/test_bot_connections_repository.py` (new)

**Interfaces:**
- Produces (on `MatchRepository` and `InMemoryMatchRepository`):
  - `create_bot_connection(url: str) -> Dict[str, Any]` — returns `{"id": str, "url": str, "createdAt": str}`
  - `list_bot_connections() -> List[Dict[str, Any]]` — sorted by `createdAt` ascending (oldest first; this ordering is the "first connection wins" collision rule later)
  - `delete_bot_connection(connection_id: str) -> None` — raises `KeyError` for unknown ids

- [ ] **Step 1: Write the failing test**

Create `quality/tests/test_bot_connections_repository.py`:

```python
from __future__ import annotations

import unittest

from ticket_to_ride.backend.repository import InMemoryMatchRepository


class BotConnectionRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMatchRepository()

    def test_created_connections_are_listed_oldest_first(self) -> None:
        first = self.repository.create_bot_connection("http://friend-a:8001")
        second = self.repository.create_bot_connection("http://friend-b:8001")

        listed = self.repository.list_bot_connections()

        self.assertEqual([record["id"] for record in listed], [first["id"], second["id"]])
        self.assertEqual(listed[0]["url"], "http://friend-a:8001")
        self.assertTrue(listed[0]["createdAt"])

    def test_delete_removes_the_connection(self) -> None:
        record = self.repository.create_bot_connection("http://friend-a:8001")

        self.repository.delete_bot_connection(record["id"])

        self.assertEqual(self.repository.list_bot_connections(), [])

    def test_delete_unknown_connection_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            self.repository.delete_bot_connection("nope")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --with pytest pytest quality/tests/test_bot_connections_repository.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'create_bot_connection'`.

- [ ] **Step 3: Implement**

In `BACKEND/repository.py`, add to the `MatchRepository` ABC (after `get_bot`):

```python
    @abstractmethod
    def create_bot_connection(self, url: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_bot_connections(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def delete_bot_connection(self, connection_id: str) -> None:
        raise NotImplementedError
```

In `InMemoryMatchRepository.__init__`, add `self.bot_connections: Dict[str, Dict[str, Any]] = {}`. Add methods (after `get_bot`):

```python
    def create_bot_connection(self, url: str) -> Dict[str, Any]:
        record = {"id": str(uuid4()), "url": url, "createdAt": utc_now_iso()}
        self.bot_connections[record["id"]] = record
        return deepcopy(record)

    def list_bot_connections(self) -> List[Dict[str, Any]]:
        return sorted(
            (deepcopy(record) for record in self.bot_connections.values()),
            key=lambda record: record["createdAt"],
        )

    def delete_bot_connection(self, connection_id: str) -> None:
        if connection_id not in self.bot_connections:
            raise KeyError(f"Unknown bot connection '{connection_id}'")
        del self.bot_connections[connection_id]
```

Note: `utc_now_iso` has microsecond precision, so two back-to-back creations sort stably.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest quality/tests/test_bot_connections_repository.py -q`
Expected: PASS. (Other repository consumers are unaffected — the new ABC methods must also be stubbed nowhere else; `PocketBaseMatchRepository` now fails to instantiate ONLY if something abstract is unimplemented — Python ABCs enforce this at instantiation, so also add the PocketBase implementations in Task 3 before running the full suite. For this task run only the file above plus `quality/tests/test_managed_match_api.py -q` which uses `InMemoryMatchRepository`.)

**Important:** adding abstract methods breaks `PocketBaseMatchRepository()` instantiation (used in `test_pocketbase_repository.py`). To keep the suite green within this task, add the three PocketBase methods here too — they are specified in Task 3 Step 3; copy them verbatim from there into this task's implementation step, then Task 3 only covers the schema + PocketBase tests.

- [ ] **Step 5: Run the broader check**

Run: `uv run --with pytest pytest quality/tests/test_bot_connections_repository.py quality/tests/test_pocketbase_repository.py quality/tests/test_managed_match_api.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add quality/tests/test_bot_connections_repository.py services/native-runtime/src/ticket_to_ride/backend/repository.py services/native-runtime/src/ticket_to_ride/backend/pocketbase.py
git commit -m "feat: persist bot connections in match repositories"
```

---

### Task 3: PocketBase `bot_connections` collection + repository coverage

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/backend/bootstrap_pocketbase.py`
- Modify: `services/native-runtime/src/ticket_to_ride/backend/pocketbase.py` (methods may already exist from Task 2 — verify they match)
- Test: `quality/tests/test_pocketbase_schema.py` (modify)
- Test: `quality/tests/test_pocketbase_repository.py` (modify)

**Interfaces:**
- Consumes: repository method contracts from Task 2.
- Produces: `bot_connections` PocketBase collection `{url: text required}`; `PocketBaseMatchRepository.{create,list,delete}_bot_connection` with normalized records `{"id", "url", "createdAt"}`.

- [ ] **Step 1: Write the failing tests**

In `quality/tests/test_pocketbase_schema.py`, the existing tests assert exact collection-name lists. Update them to include `bot_connections`:
- Where a test asserts reset order `["managed_rounds", "managed_matches", "turns", "rounds", "matches", "bots"]`, change to `["bot_connections", "managed_rounds", "managed_matches", "turns", "rounds", "matches", "bots"]`.
- Where a test asserts created names `["bots", "matches", "rounds", "turns", "managed_matches", "managed_rounds"]`, change to `["bots", "matches", "rounds", "turns", "managed_matches", "managed_rounds", "bot_connections"]`.
- Add a new test to the schema test class:

```python
    def test_bot_connections_collection_has_a_url_field(self) -> None:
        bot_connections = next(
            collection for collection in COLLECTIONS if collection["name"] == "bot_connections"
        )

        field_names = {field["name"] for field in bot_connections["fields"]}
        self.assertEqual(field_names, {"url"})
```

In `quality/tests/test_pocketbase_repository.py`, add:

```python
    def test_bot_connection_round_trip_uses_the_bot_connections_collection(self) -> None:
        repository = PocketBaseMatchRepository("http://127.0.0.1:8090")

        with patch.object(
            repository,
            "_request_json",
            return_value={"id": "conn1", "url": "http://friend-a:8001", "created": "2026-07-19 10:00:00.000Z"},
        ) as request_json:
            record = repository.create_bot_connection("http://friend-a:8001")

        request_json.assert_called_once_with(
            "POST", "/api/collections/bot_connections/records", {"url": "http://friend-a:8001"}
        )
        self.assertEqual(record, {"id": "conn1", "url": "http://friend-a:8001", "createdAt": "2026-07-19 10:00:00.000Z"})

    def test_delete_unknown_bot_connection_raises_key_error(self) -> None:
        from ticket_to_ride.backend.pocketbase import PocketBaseError

        repository = PocketBaseMatchRepository("http://127.0.0.1:8090")

        with patch.object(
            repository,
            "_request_json",
            side_effect=PocketBaseError("PocketBase request failed (404): missing"),
        ):
            with self.assertRaises(KeyError):
                repository.delete_bot_connection("nope")
```

- [ ] **Step 2: Run the tests to verify failures**

Run: `uv run --with pytest pytest quality/tests/test_pocketbase_schema.py quality/tests/test_pocketbase_repository.py -q`
Expected: FAIL — schema tests can't find `bot_connections` in `COLLECTIONS`; repository tests fail if Task 2 didn't already add the methods, or pass if it did (then only schema fails).

- [ ] **Step 3: Implement**

In `BACKEND/bootstrap_pocketbase.py`:
- Append to `COLLECTIONS` (after the `managed_rounds` entry):

```python
    {
        "name": "bot_connections",
        "type": "base",
        "fields": [
            {"name": "url", "type": "text", "required": True},
        ],
    },
```

- In `reset_project_collections`, change the deletion-order tuple to:

```python
    for collection_name in ("bot_connections", "managed_rounds", "managed_matches", "turns", "rounds", "matches", "bots"):
```

In `BACKEND/pocketbase.py` (if not already added in Task 2), add after `get_bot`:

```python
    def create_bot_connection(self, url: str) -> Dict[str, Any]:
        record = self._request_json("POST", "/api/collections/bot_connections/records", {"url": url})
        return self._normalize_bot_connection(record)

    def list_bot_connections(self) -> List[Dict[str, Any]]:
        records = self._request_all_items("/api/collections/bot_connections/records")
        connections = [self._normalize_bot_connection(record) for record in records]
        return sorted(connections, key=lambda connection: connection["createdAt"])

    def delete_bot_connection(self, connection_id: str) -> None:
        try:
            self._request_json("DELETE", f"/api/collections/bot_connections/records/{connection_id}")
        except PocketBaseError as exc:
            if "(404)" in str(exc):
                raise KeyError(f"Unknown bot connection '{connection_id}'") from exc
            raise
```

And add the normalizer next to `_normalize_bot`:

```python
    @staticmethod
    def _normalize_bot_connection(record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": record["id"],
            "url": (record.get("url") or "").rstrip("/"),
            "createdAt": record.get("created") or record.get("createdAt") or "",
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest quality/tests/test_pocketbase_schema.py quality/tests/test_pocketbase_repository.py quality/tests/test_bot_connections_repository.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/backend/bootstrap_pocketbase.py services/native-runtime/src/ticket_to_ride/backend/pocketbase.py quality/tests/test_pocketbase_schema.py quality/tests/test_pocketbase_repository.py
git commit -m "feat: add bot_connections PocketBase collection and repository support"
```

---

### Task 4: Bot scaffolding module

Stamp `integrations/external/templates/bots/build_your_bot_here.py` into `integrations/external/bots/<slug>.py`. The template's replaceable placeholders are exactly: `"id": "your_bot_id"`, `"name": "Your Bot Name"`, and the class name `YourBotName` (3 occurrences).

**Files:**
- Create: `services/native-runtime/src/ticket_to_ride/backend/bot_scaffold.py`
- Test: `quality/tests/test_bot_scaffold.py` (new)

**Interfaces:**
- Produces:
  - `slugify_bot_name(name: str) -> str` — raises `BotScaffoldError` when no alphanumerics remain
  - `class_name_from_slug(slug: str) -> str` — `my_cool_bot` → `MyCoolBot`
  - `scaffold_bot(name: str, *, bots_dir: Path | None = None, template_path: Path | None = None) -> ScaffoldedBot` — `ScaffoldedBot(bot_id: str, name: str, path: str)`
  - `class BotScaffoldError(ValueError)` — endpoints later map `ValueError` → HTTP 400

- [ ] **Step 1: Write the failing test**

Create `quality/tests/test_bot_scaffold.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ticket_to_ride.backend.bot_scaffold import (
    BotScaffoldError,
    class_name_from_slug,
    scaffold_bot,
    slugify_bot_name,
)


class SlugifyTests(unittest.TestCase):
    def test_names_are_lowercased_and_joined_with_underscores(self) -> None:
        self.assertEqual(slugify_bot_name("My Cool Bot"), "my_cool_bot")
        self.assertEqual(slugify_bot_name("  spaced   out  "), "spaced_out")
        self.assertEqual(slugify_bot_name("Ticket-2-Ride!"), "ticket_2_ride")

    def test_leading_digit_gets_a_bot_prefix(self) -> None:
        self.assertEqual(slugify_bot_name("2fast"), "bot_2fast")

    def test_name_without_alphanumerics_is_rejected(self) -> None:
        with self.assertRaises(BotScaffoldError):
            slugify_bot_name("!!!")

    def test_class_name_is_camel_cased(self) -> None:
        self.assertEqual(class_name_from_slug("my_cool_bot"), "MyCoolBot")


class ScaffoldBotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.bots_dir = Path(self._tmp.name)

    def test_scaffold_writes_a_notebook_with_substituted_metadata(self) -> None:
        scaffolded = scaffold_bot("My Cool Bot", bots_dir=self.bots_dir)

        self.assertEqual(scaffolded.bot_id, "my_cool_bot")
        self.assertEqual(scaffolded.name, "My Cool Bot")
        target = self.bots_dir / "my_cool_bot.py"
        self.assertEqual(scaffolded.path, str(target))
        source = target.read_text(encoding="utf-8")
        self.assertIn('"id": "my_cool_bot"', source)
        self.assertIn('"name": "My Cool Bot"', source)
        self.assertIn("class MyCoolBot(ActionBot):", source)
        self.assertNotIn("your_bot_id", source)
        self.assertNotIn("YourBotName", source)

    def test_scaffold_rejects_an_existing_bot_file(self) -> None:
        scaffold_bot("My Cool Bot", bots_dir=self.bots_dir)

        with self.assertRaises(BotScaffoldError):
            scaffold_bot("my cool BOT", bots_dir=self.bots_dir)

    def test_scaffold_rejects_empty_and_quoted_names(self) -> None:
        with self.assertRaises(BotScaffoldError):
            scaffold_bot("   ", bots_dir=self.bots_dir)
        with self.assertRaises(BotScaffoldError):
            scaffold_bot('Nasty "Bot"', bots_dir=self.bots_dir)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --with pytest pytest quality/tests/test_bot_scaffold.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ticket_to_ride.backend.bot_scaffold'`.

- [ ] **Step 3: Implement**

Create `BACKEND/bot_scaffold.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class BotScaffoldError(ValueError):
    """Raised when a new bot cannot be scaffolded from the template."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _default_bots_dir() -> Path:
    return _repo_root() / "integrations" / "external" / "bots"


def _default_template_path() -> Path:
    return _repo_root() / "integrations" / "external" / "templates" / "bots" / "build_your_bot_here.py"


def slugify_bot_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if not slug:
        raise BotScaffoldError("Bot name must contain at least one letter or number.")
    if slug[0].isdigit():
        slug = f"bot_{slug}"
    return slug


def class_name_from_slug(slug: str) -> str:
    return "".join(part.capitalize() for part in slug.split("_") if part)


@dataclass(frozen=True)
class ScaffoldedBot:
    bot_id: str
    name: str
    path: str


def scaffold_bot(
    name: str,
    *,
    bots_dir: Path | None = None,
    template_path: Path | None = None,
) -> ScaffoldedBot:
    display_name = name.strip()
    if not display_name:
        raise BotScaffoldError("Bot name is required.")
    if '"' in display_name or "\\" in display_name:
        raise BotScaffoldError("Bot name must not contain quotes or backslashes.")

    slug = slugify_bot_name(display_name)
    resolved_bots_dir = bots_dir or _default_bots_dir()
    target_path = resolved_bots_dir / f"{slug}.py"
    if target_path.exists():
        raise BotScaffoldError(f"A bot module named '{slug}' already exists.")

    source = (template_path or _default_template_path()).read_text(encoding="utf-8")
    source = source.replace('"id": "your_bot_id"', f'"id": "{slug}"')
    source = source.replace('"name": "Your Bot Name"', f'"name": "{display_name}"')
    source = source.replace("YourBotName", class_name_from_slug(slug))
    target_path.write_text(source, encoding="utf-8")
    return ScaffoldedBot(bot_id=slug, name=display_name, path=str(target_path))
```

Note on `parents[5]`: this file lives in `services/native-runtime/src/ticket_to_ride/backend/`, so `parents[5]` is the repo root — the same convention `notebook_launcher.py` uses in the same directory.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest quality/tests/test_bot_scaffold.py quality/tests/test_bot_template.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/backend/bot_scaffold.py quality/tests/test_bot_scaffold.py
git commit -m "feat: add bot scaffolding from the build-your-bot template"
```

---

### Task 5: BotDirectory — live merged view of local bots and connections

**Files:**
- Create: `services/native-runtime/src/ticket_to_ride/backend/bot_directory.py`
- Test: `quality/tests/test_bot_directory.py` (new)

**Interfaces:**
- Consumes: `repository.list_bot_connections()` (Task 2), `LocalApiBotCatalogClient(..., require_loopback=False)` (Task 1), `build_bot_catalog_client_from_env` and `BotCatalogRecord` from `bot_catalog.py`.
- Produces:
  - `DirectoryBot(bot_id, name, version, description, author, tags, source, connection_id, base_url, module_path)` — `source` is `"local"` or `"remote"`; `connection_id`/`base_url` are `None` for local bots; `module_path` is `""` for remote bots
  - `ConnectionStatus(connection_id, url, status, error, bot_count, created_at)` — `status` is `"online"` or `"offline"`
  - `DirectoryListing(bots: List[DirectoryBot], connections: List[ConnectionStatus])`
  - `BotDirectory(repository, *, local_catalog_factory=None, remote_catalog_factory=None)` with `list_all() -> DirectoryListing` and `resolve(bot_id) -> DirectoryBot` (raises `KeyError`)
  - `default_remote_catalog_factory(url) -> BotCatalogClient`
  - Collision rule: local bots shadow remote; among connections, the oldest connection wins. `bot_count` reports how many bots the connection advertises (before shadowing).

- [ ] **Step 1: Write the failing test**

Create `quality/tests/test_bot_directory.py`:

```python
from __future__ import annotations

import unittest

from ticket_to_ride.backend.bot_catalog import BotCatalogError, BotCatalogRecord
from ticket_to_ride.backend.bot_directory import BotDirectory
from ticket_to_ride.backend.repository import InMemoryMatchRepository


def catalog_record(bot_id: str, name: str, base_url: str = "http://127.0.0.1:8001") -> BotCatalogRecord:
    return BotCatalogRecord(
        schema_version=1,
        bot_id=bot_id,
        name=name,
        version="1.0.0",
        description=f"{name} description",
        author="Author",
        tags=["test"],
        source_kind="local_api",
        source_base_url=base_url,
        discovery_path="/bots",
        module_path=f"/repo/integrations/external/bots/{bot_id}.py",
    )


class StaticCatalog:
    def __init__(self, records):
        self.records = list(records)

    def list_bots(self):
        return list(self.records)

    def resolve_bot(self, bot_id: str):
        for record in self.records:
            if record.bot_id == bot_id:
                return record
        raise KeyError(bot_id)


class FailingCatalog:
    def list_bots(self):
        raise BotCatalogError("connection refused")

    def resolve_bot(self, bot_id: str):
        raise BotCatalogError("connection refused")


def build_directory(repository, local_records, remote_catalogs):
    return BotDirectory(
        repository,
        local_catalog_factory=lambda: StaticCatalog(local_records),
        remote_catalog_factory=lambda url: remote_catalogs[url],
    )


class BotDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMatchRepository()

    def test_local_bots_are_listed_without_connections(self) -> None:
        directory = build_directory(self.repository, [catalog_record("random_bot", "Random Bot")], {})

        listing = directory.list_all()

        self.assertEqual([bot.bot_id for bot in listing.bots], ["random_bot"])
        self.assertEqual(listing.bots[0].source, "local")
        self.assertIsNone(listing.bots[0].connection_id)
        self.assertEqual(listing.connections, [])

    def test_online_connection_contributes_remote_bots(self) -> None:
        connection = self.repository.create_bot_connection("http://friend-a:8001")
        directory = build_directory(
            self.repository,
            [catalog_record("random_bot", "Random Bot")],
            {"http://friend-a:8001": StaticCatalog([catalog_record("friend_bot", "Friend Bot")])},
        )

        listing = directory.list_all()

        remote = next(bot for bot in listing.bots if bot.bot_id == "friend_bot")
        self.assertEqual(remote.source, "remote")
        self.assertEqual(remote.connection_id, connection["id"])
        self.assertEqual(remote.base_url, "http://friend-a:8001")
        self.assertEqual(len(listing.connections), 1)
        self.assertEqual(listing.connections[0].status, "online")
        self.assertEqual(listing.connections[0].bot_count, 1)

    def test_offline_connection_is_reported_without_bots(self) -> None:
        self.repository.create_bot_connection("http://friend-a:8001")
        directory = build_directory(
            self.repository,
            [catalog_record("random_bot", "Random Bot")],
            {"http://friend-a:8001": FailingCatalog()},
        )

        listing = directory.list_all()

        self.assertEqual([bot.bot_id for bot in listing.bots], ["random_bot"])
        self.assertEqual(listing.connections[0].status, "offline")
        self.assertIn("connection refused", listing.connections[0].error)

    def test_local_bots_shadow_remote_bots_with_the_same_id(self) -> None:
        self.repository.create_bot_connection("http://friend-a:8001")
        directory = build_directory(
            self.repository,
            [catalog_record("random_bot", "Random Bot")],
            {"http://friend-a:8001": StaticCatalog([catalog_record("random_bot", "Impostor Bot")])},
        )

        listing = directory.list_all()

        matches = [bot for bot in listing.bots if bot.bot_id == "random_bot"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].source, "local")
        self.assertEqual(listing.connections[0].bot_count, 1)

    def test_oldest_connection_wins_duplicate_remote_ids(self) -> None:
        self.repository.create_bot_connection("http://friend-a:8001")
        self.repository.create_bot_connection("http://friend-b:8001")
        directory = build_directory(
            self.repository,
            [],
            {
                "http://friend-a:8001": StaticCatalog([catalog_record("friend_bot", "First Friend")]),
                "http://friend-b:8001": StaticCatalog([catalog_record("friend_bot", "Second Friend")]),
            },
        )

        listing = directory.list_all()

        matches = [bot for bot in listing.bots if bot.bot_id == "friend_bot"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].base_url, "http://friend-a:8001")

    def test_resolve_finds_bots_case_insensitively(self) -> None:
        directory = build_directory(self.repository, [catalog_record("random_bot", "Random Bot")], {})

        self.assertEqual(directory.resolve("Random_Bot").bot_id, "random_bot")
        with self.assertRaises(KeyError):
            directory.resolve("missing_bot")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --with pytest pytest quality/tests/test_bot_directory.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ticket_to_ride.backend.bot_directory'`.

- [ ] **Step 3: Implement**

Create `BACKEND/bot_directory.py`:

```python
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ticket_to_ride.backend.bot_catalog import (
    BotCatalogClient,
    BotCatalogRecord,
    LocalApiBotCatalogClient,
    build_bot_catalog_client_from_env,
)
from ticket_to_ride.backend.repository import MatchRepository

logger = logging.getLogger(__name__)

REMOTE_TIMEOUT_SECONDS = 3
MAX_CONCURRENT_CONNECTION_FETCHES = 8


@dataclass(frozen=True)
class DirectoryBot:
    bot_id: str
    name: str
    version: str
    description: str
    author: str
    tags: List[str]
    source: str
    connection_id: Optional[str]
    base_url: Optional[str]
    module_path: str


@dataclass(frozen=True)
class ConnectionStatus:
    connection_id: str
    url: str
    status: str
    error: Optional[str]
    bot_count: int
    created_at: str


@dataclass(frozen=True)
class DirectoryListing:
    bots: List[DirectoryBot]
    connections: List[ConnectionStatus]


def default_remote_catalog_factory(url: str) -> BotCatalogClient:
    return LocalApiBotCatalogClient(url, require_loopback=False, timeout_seconds=REMOTE_TIMEOUT_SECONDS)


def _local_bot(record: BotCatalogRecord) -> DirectoryBot:
    return DirectoryBot(
        bot_id=record.bot_id,
        name=record.name,
        version=record.version,
        description=record.description,
        author=record.author,
        tags=list(record.tags),
        source="local",
        connection_id=None,
        base_url=None,
        module_path=record.module_path,
    )


def _remote_bot(record: BotCatalogRecord, connection: Dict[str, Any]) -> DirectoryBot:
    return DirectoryBot(
        bot_id=record.bot_id,
        name=record.name,
        version=record.version,
        description=record.description,
        author=record.author,
        tags=list(record.tags),
        source="remote",
        connection_id=connection["id"],
        base_url=connection["url"],
        module_path="",
    )


class BotDirectory:
    """Live merged view of locally discoverable bots and remote bot connections.

    Local bots are rediscovered on every call (fresh catalog client per call);
    connections are pinged concurrently so one dead host does not stall listing.
    """

    def __init__(
        self,
        repository: MatchRepository,
        *,
        local_catalog_factory: Optional[Callable[[], BotCatalogClient]] = None,
        remote_catalog_factory: Optional[Callable[[str], BotCatalogClient]] = None,
    ) -> None:
        self.repository = repository
        self.local_catalog_factory = local_catalog_factory or build_bot_catalog_client_from_env
        self.remote_catalog_factory = remote_catalog_factory or default_remote_catalog_factory

    def list_all(self) -> DirectoryListing:
        bots: Dict[str, DirectoryBot] = {}
        for record in self.local_catalog_factory().list_bots():
            bots[record.bot_id] = _local_bot(record)

        connection_records = self.repository.list_bot_connections()
        connections: List[ConnectionStatus] = []
        for connection, result in zip(connection_records, self._fetch_all(connection_records)):
            if isinstance(result, Exception):
                connections.append(
                    ConnectionStatus(
                        connection_id=connection["id"],
                        url=connection["url"],
                        status="offline",
                        error=str(result),
                        bot_count=0,
                        created_at=connection["createdAt"],
                    )
                )
                continue

            for record in result:
                if record.bot_id in bots:
                    logger.warning(
                        "Bot id '%s' from connection %s is shadowed by an earlier source.",
                        record.bot_id,
                        connection["url"],
                    )
                    continue
                bots[record.bot_id] = _remote_bot(record, connection)

            connections.append(
                ConnectionStatus(
                    connection_id=connection["id"],
                    url=connection["url"],
                    status="online",
                    error=None,
                    bot_count=len(result),
                    created_at=connection["createdAt"],
                )
            )

        sorted_bots = sorted(bots.values(), key=lambda bot: (bot.name.casefold(), bot.bot_id.casefold()))
        return DirectoryListing(bots=sorted_bots, connections=connections)

    def resolve(self, bot_id: str) -> DirectoryBot:
        requested = bot_id.strip()
        if not requested:
            raise KeyError("Bot ID is required.")
        requested_key = requested.casefold()
        for bot in self.list_all().bots:
            if bot.bot_id.casefold() == requested_key:
                return bot
        raise KeyError(f"Unknown bot '{requested}'.")

    def _fetch_all(self, connection_records: List[Dict[str, Any]]) -> List[Any]:
        if not connection_records:
            return []

        def fetch(record: Dict[str, Any]) -> List[BotCatalogRecord]:
            return self.remote_catalog_factory(record["url"]).list_bots()

        max_workers = min(len(connection_records), MAX_CONCURRENT_CONNECTION_FETCHES)
        results: List[Any] = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(fetch, record) for record in connection_records]
            for future in futures:
                try:
                    results.append(future.result())
                except Exception as exc:  # offline connections must not break listing
                    results.append(exc)
        return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest quality/tests/test_bot_directory.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/backend/bot_directory.py quality/tests/test_bot_directory.py
git commit -m "feat: add BotDirectory merging live local discovery with remote connections"
```

---

### Task 6: Rework the bots API — merged listing, new-bot, connections

Replace the register-by-ID flow with the directory. This task touches models, service, and app together because the endpoints only compile as a set.

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/backend/models.py`
- Modify: `services/native-runtime/src/ticket_to_ride/backend/service.py`
- Modify: `services/native-runtime/src/ticket_to_ride/backend/app.py`
- Delete: `quality/tests/test_bot_registry_api.py`
- Test: `quality/tests/test_bot_directory_api.py` (new)
- Test: `quality/tests/test_notebook_launch_api.py` (modify)

**Interfaces:**
- Consumes: `BotDirectory`, `DirectoryBot`, `ConnectionStatus`, `DirectoryListing` (Task 5); `scaffold_bot`, `BotScaffoldError` (Task 4).
- Produces (Pydantic models in `models.py`; `BotSummary` and `BotRegisterRequest` are REMOVED):

```python
class BotEntry(BaseModel):
    botId: str
    name: str
    version: str
    description: str
    author: str = ""
    tags: List[str] = Field(default_factory=list)
    source: Literal["local", "remote"]
    connectionId: Optional[str] = None
    baseUrl: Optional[str] = None


class ConnectionSummary(BaseModel):
    connectionId: str
    url: str
    status: Literal["online", "offline"]
    error: Optional[str] = None
    botCount: int = 0
    createdAt: str = ""


class BotListResponse(BaseModel):
    bots: List[BotEntry] = Field(default_factory=list)
    connections: List[ConnectionSummary] = Field(default_factory=list)


class BotCreateRequest(BaseModel):
    name: str


class BotCreateResponse(BaseModel):
    botId: str
    url: str


class ConnectionCreateRequest(BaseModel):
    url: str


class ConnectionCreateResponse(BaseModel):
    connection: ConnectionSummary
    bots: List[BotEntry] = Field(default_factory=list)
```

- Produces (service functions; `list_bots`, `register_bot`, `build_bot_summary` are REMOVED):
  - `list_bot_directory(directory: BotDirectory) -> BotListResponse`
  - `create_bot(notebook_launcher: NotebookLauncher, name: str) -> BotCreateResponse` (calls `scaffold_bot(name)` then `notebook_launcher.launch`; tests patch `ticket_to_ride.backend.service.scaffold_bot`)
  - `add_bot_connection(repository, directory, url: str) -> ConnectionCreateResponse` (raises `ValueError` for bad scheme/duplicate/unreachable)
  - `remove_bot_connection(repository, connection_id: str) -> None` (raises `ConnectionNotFoundError`)
  - `class ConnectionNotFoundError(LookupError)`
  - `launch_notebook(directory: BotDirectory, notebook_launcher, bot_id) -> NotebookLaunchResponse` — signature changes from catalog client to directory; remote bots raise `ValueError("Only local bots have notebooks to open.")`
- Produces (endpoints): `GET /bots -> BotListResponse`; `POST /bots/new`; `POST /bot-connections`; `DELETE /bot-connections/{connection_id}` (returns `{"status": "deleted"}`); `POST /bots` is GONE. `create_app` signature: `create_app(repository=None, bot_directory=None, runtime_manager=None, notebook_launcher=None)` — the `bot_catalog_client` parameter is REMOVED; `app.state.bot_directory` replaces `app.state.bot_catalog_client`.

- [ ] **Step 1: Write the failing API tests**

Delete `quality/tests/test_bot_registry_api.py` (its flow no longer exists; its loopback-env test moved to `test_bot_catalog_remote.py` coverage in Task 1). Create `quality/tests/test_bot_directory_api.py`:

```python
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ticket_to_ride.backend.app import create_app
from ticket_to_ride.backend.bot_catalog import BotCatalogError, BotCatalogRecord
from ticket_to_ride.backend.bot_directory import BotDirectory
from ticket_to_ride.backend.bot_scaffold import BotScaffoldError, ScaffoldedBot
from ticket_to_ride.backend.notebook_launcher import NotebookLauncher
from ticket_to_ride.backend.repository import InMemoryMatchRepository


def catalog_record(bot_id: str, name: str) -> BotCatalogRecord:
    return BotCatalogRecord(
        schema_version=1,
        bot_id=bot_id,
        name=name,
        version="1.0.0",
        description=f"{name} description",
        author="Author",
        tags=["test"],
        source_kind="local_api",
        source_base_url="http://127.0.0.1:8001",
        discovery_path="/bots",
        module_path=f"/repo/integrations/external/bots/{bot_id}.py",
    )


class StaticCatalog:
    def __init__(self, records):
        self.records = list(records)

    def list_bots(self):
        return list(self.records)

    def resolve_bot(self, bot_id: str):
        for record in self.records:
            if record.bot_id == bot_id:
                return record
        raise KeyError(bot_id)


class FailingCatalog:
    def list_bots(self):
        raise BotCatalogError("connection refused")

    def resolve_bot(self, bot_id: str):
        raise BotCatalogError("connection refused")


class FakeNotebookLauncher(NotebookLauncher):
    def __init__(self) -> None:
        self.launch_calls = []

    def launch(self, bot_id: str, notebook_path: str) -> str:
        self.launch_calls.append((bot_id, notebook_path))
        return "http://127.0.0.1:2718"


def build_client(repository, local_records, remote_catalogs, notebook_launcher=None):
    directory = BotDirectory(
        repository,
        local_catalog_factory=lambda: StaticCatalog(local_records),
        remote_catalog_factory=lambda url: remote_catalogs[url],
    )
    return TestClient(
        create_app(
            repository=repository,
            bot_directory=directory,
            notebook_launcher=notebook_launcher or FakeNotebookLauncher(),
        )
    )


class BotListingApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMatchRepository()

    def test_local_bots_are_listed_without_registration(self) -> None:
        client = build_client(self.repository, [catalog_record("random_bot", "Random Bot")], {})

        response = client.get("/bots")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["bots"]), 1)
        self.assertEqual(payload["bots"][0]["botId"], "random_bot")
        self.assertEqual(payload["bots"][0]["source"], "local")
        self.assertIsNone(payload["bots"][0]["connectionId"])
        self.assertEqual(payload["connections"], [])

    def test_connections_report_status_and_remote_bots(self) -> None:
        online = self.repository.create_bot_connection("http://friend-a:8001")
        self.repository.create_bot_connection("http://friend-b:8001")
        client = build_client(
            self.repository,
            [catalog_record("random_bot", "Random Bot")],
            {
                "http://friend-a:8001": StaticCatalog([catalog_record("friend_bot", "Friend Bot")]),
                "http://friend-b:8001": FailingCatalog(),
            },
        )

        payload = client.get("/bots").json()

        by_id = {bot["botId"]: bot for bot in payload["bots"]}
        self.assertEqual(by_id["friend_bot"]["source"], "remote")
        self.assertEqual(by_id["friend_bot"]["connectionId"], online["id"])
        self.assertEqual(by_id["friend_bot"]["baseUrl"], "http://friend-a:8001")
        statuses = {connection["url"]: connection["status"] for connection in payload["connections"]}
        self.assertEqual(statuses, {"http://friend-a:8001": "online", "http://friend-b:8001": "offline"})


class NewBotApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMatchRepository()
        self.notebook_launcher = FakeNotebookLauncher()
        self.client = build_client(self.repository, [], {}, notebook_launcher=self.notebook_launcher)

    def test_new_bot_is_scaffolded_and_its_notebook_opened(self) -> None:
        scaffolded = ScaffoldedBot(bot_id="my_cool_bot", name="My Cool Bot", path="/repo/bots/my_cool_bot.py")

        with patch("ticket_to_ride.backend.service.scaffold_bot", return_value=scaffolded) as scaffold:
            response = self.client.post("/bots/new", json={"name": "My Cool Bot"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"botId": "my_cool_bot", "url": "http://127.0.0.1:2718"})
        scaffold.assert_called_once_with("My Cool Bot")
        self.assertEqual(self.notebook_launcher.launch_calls, [("my_cool_bot", "/repo/bots/my_cool_bot.py")])

    def test_invalid_bot_name_returns_bad_request(self) -> None:
        with patch("ticket_to_ride.backend.service.scaffold_bot", side_effect=BotScaffoldError("Bot name is required.")):
            response = self.client.post("/bots/new", json={"name": "   "})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Bot name is required.")


class ConnectionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMatchRepository()

    def test_add_connection_pings_and_persists(self) -> None:
        client = build_client(
            self.repository,
            [],
            {"http://friend-a:8001": StaticCatalog([catalog_record("friend_bot", "Friend Bot")])},
        )

        response = client.post("/bot-connections", json={"url": "http://friend-a:8001/"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["connection"]["url"], "http://friend-a:8001")
        self.assertEqual(payload["connection"]["status"], "online")
        self.assertEqual(payload["connection"]["botCount"], 1)
        self.assertEqual(payload["bots"][0]["botId"], "friend_bot")
        self.assertEqual(len(self.repository.list_bot_connections()), 1)

    def test_duplicate_connection_url_is_rejected(self) -> None:
        self.repository.create_bot_connection("http://friend-a:8001")
        client = build_client(
            self.repository,
            [],
            {"http://friend-a:8001": StaticCatalog([])},
        )

        response = client.post("/bot-connections", json={"url": "http://friend-a:8001"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("already", response.json()["detail"])

    def test_unreachable_connection_is_rejected(self) -> None:
        client = build_client(self.repository, [], {"http://friend-a:8001": FailingCatalog()})

        response = client.post("/bot-connections", json={"url": "http://friend-a:8001"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.repository.list_bot_connections(), [])

    def test_non_http_url_is_rejected(self) -> None:
        client = build_client(self.repository, [], {})

        response = client.post("/bot-connections", json={"url": "ftp://friend-a:8001"})

        self.assertEqual(response.status_code, 400)

    def test_delete_connection(self) -> None:
        record = self.repository.create_bot_connection("http://friend-a:8001")
        client = build_client(self.repository, [], {"http://friend-a:8001": StaticCatalog([])})

        response = client.delete(f"/bot-connections/{record['id']}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.repository.list_bot_connections(), [])

    def test_delete_unknown_connection_returns_not_found(self) -> None:
        client = build_client(self.repository, [], {})

        response = client.delete("/bot-connections/nope")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Update the notebook launch tests**

In `quality/tests/test_notebook_launch_api.py`:
- Replace the `StaticCatalogClient` injection with a `BotDirectory` built from it. Change imports to add `from ticket_to_ride.backend.bot_directory import BotDirectory`, and in every `create_app(...)` call replace `bot_catalog_client=StaticCatalogClient([...])` with:

```python
                bot_directory=BotDirectory(
                    self.repository,
                    local_catalog_factory=lambda: StaticCatalogClient(
                        [build_catalog_record("random_bot", "/repo/integrations/external/bots/random_bot.py")]
                    ),
                    remote_catalog_factory=lambda url: (_ for _ in ()).throw(AssertionError("no remote calls expected")),
                ),
```

  (for the unknown-bot test, the factory returns `StaticCatalogClient([])`). Keep all assertions unchanged. Add one new test:

```python
    def test_launch_rejects_remote_bots(self) -> None:
        from ticket_to_ride.backend.bot_catalog import BotCatalogRecord

        self.repository.create_bot_connection("http://friend-a:8001")
        remote_record = build_catalog_record("friend_bot", "")
        client = TestClient(
            create_app(
                repository=self.repository,
                bot_directory=BotDirectory(
                    self.repository,
                    local_catalog_factory=lambda: StaticCatalogClient([]),
                    remote_catalog_factory=lambda url: StaticCatalogClient([remote_record]),
                ),
                notebook_launcher=self.notebook_launcher,
            )
        )

        response = client.post("/notebooks/friend_bot/launch")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.spawn_calls, [])
```

- [ ] **Step 3: Run the tests to verify failures**

Run: `uv run --with pytest pytest quality/tests/test_bot_directory_api.py quality/tests/test_notebook_launch_api.py -q`
Expected: FAIL — `create_app` has no `bot_directory` parameter; service functions missing.

- [ ] **Step 4: Implement models**

In `BACKEND/models.py`: delete `BotRegisterRequest` and `BotSummary`; add the eight models exactly as written in this task's **Interfaces** block, in their place. Keep `NotebookLaunchResponse` unchanged.

- [ ] **Step 5: Implement service functions**

In `BACKEND/service.py`:
- Update imports: remove `BotSummary`/`BotRegisterRequest`-related imports; add:

```python
from urllib.parse import urlparse

from ticket_to_ride.backend.bot_catalog import BotCatalogError
from ticket_to_ride.backend.bot_directory import BotDirectory, ConnectionStatus, DirectoryBot
from ticket_to_ride.backend.bot_scaffold import scaffold_bot
from ticket_to_ride.backend.models import (
    BotCreateResponse,
    BotEntry,
    BotListResponse,
    ConnectionCreateResponse,
    ConnectionSummary,
    ...,  # keep the existing model imports minus BotSummary
)
```

- Delete `build_bot_summary`, `list_bots`, `register_bot`. Add:

```python
class ConnectionNotFoundError(LookupError):
    """Raised when a requested bot connection does not exist."""


def _bot_entry(bot: DirectoryBot) -> BotEntry:
    return BotEntry(
        botId=bot.bot_id,
        name=bot.name,
        version=bot.version,
        description=bot.description,
        author=bot.author,
        tags=list(bot.tags),
        source=bot.source,
        connectionId=bot.connection_id,
        baseUrl=bot.base_url,
    )


def _connection_summary(connection: ConnectionStatus) -> ConnectionSummary:
    return ConnectionSummary(
        connectionId=connection.connection_id,
        url=connection.url,
        status=connection.status,
        error=connection.error,
        botCount=connection.bot_count,
        createdAt=connection.created_at,
    )


def list_bot_directory(directory: BotDirectory) -> BotListResponse:
    listing = directory.list_all()
    return BotListResponse(
        bots=[_bot_entry(bot) for bot in listing.bots],
        connections=[_connection_summary(connection) for connection in listing.connections],
    )


def create_bot(notebook_launcher: NotebookLauncher, name: str) -> BotCreateResponse:
    scaffolded = scaffold_bot(name)
    url = notebook_launcher.launch(scaffolded.bot_id, scaffolded.path)
    return BotCreateResponse(botId=scaffolded.bot_id, url=url)


def add_bot_connection(
    repository: MatchRepository,
    directory: BotDirectory,
    url: str,
) -> ConnectionCreateResponse:
    normalized = url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Connection URL must be an http or https URL.")

    if any(record["url"] == normalized for record in repository.list_bot_connections()):
        raise ValueError("This connection is already registered.")

    try:
        remote_records = directory.remote_catalog_factory(normalized).list_bots()
    except BotCatalogError as exc:
        raise ValueError(f"Unable to reach a bot API at {normalized}: {exc}") from exc

    record = repository.create_bot_connection(normalized)
    connection = ConnectionSummary(
        connectionId=record["id"],
        url=record["url"],
        status="online",
        error=None,
        botCount=len(remote_records),
        createdAt=record["createdAt"],
    )
    bots = [
        BotEntry(
            botId=remote.bot_id,
            name=remote.name,
            version=remote.version,
            description=remote.description,
            author=remote.author,
            tags=list(remote.tags),
            source="remote",
            connectionId=record["id"],
            baseUrl=record["url"],
        )
        for remote in remote_records
    ]
    return ConnectionCreateResponse(connection=connection, bots=bots)


def remove_bot_connection(repository: MatchRepository, connection_id: str) -> None:
    try:
        repository.delete_bot_connection(connection_id)
    except KeyError as exc:
        raise ConnectionNotFoundError(f"Unknown bot connection '{connection_id}'.") from exc
```

- Rewrite `launch_notebook` to resolve through the directory:

```python
def launch_notebook(
    directory: BotDirectory,
    notebook_launcher: NotebookLauncher,
    bot_id: str,
) -> NotebookLaunchResponse:
    requested_bot_id = bot_id.strip()
    if not requested_bot_id:
        raise ValueError("Bot ID is required.")

    try:
        bot = directory.resolve(requested_bot_id)
    except KeyError as exc:
        raise BotNotFoundError(f"Unknown bot '{requested_bot_id}'.") from exc

    if bot.source != "local" or not bot.module_path:
        raise ValueError("Only local bots have notebooks to open.")

    url = notebook_launcher.launch(bot.bot_id, bot.module_path)
    return NotebookLaunchResponse(botId=bot.bot_id, url=url)
```

- [ ] **Step 6: Implement app wiring**

In `BACKEND/app.py`:
- Imports: drop `BotRegisterRequest`, `BotSummary`, `build_bot_catalog_client_from_env`, `BotCatalogClient`, `list_bots`, `register_bot`; add `BotDirectory` from `bot_directory`, the new models (`BotCreateRequest`, `BotCreateResponse`, `BotListResponse`, `ConnectionCreateRequest`, `ConnectionCreateResponse`), and the new service functions (`add_bot_connection`, `create_bot`, `list_bot_directory`, `remove_bot_connection`, `ConnectionNotFoundError`). Keep the `BotCatalogError` import and its 503 exception handler — local discovery failures still surface through it.
- `create_app` signature and state:

```python
def create_app(
    repository: Optional[MatchRepository] = None,
    bot_directory: Optional[BotDirectory] = None,
    runtime_manager: Optional[ManagedMatchRuntimeManager] = None,
    notebook_launcher: Optional[NotebookLauncher] = None,
) -> FastAPI:
    app = FastAPI(title="Ticket to Ride Match Logger", version="1.0.0")
    app.state.match_repository = repository or build_repository_from_env()
    app.state.bot_directory = bot_directory or BotDirectory(app.state.match_repository)
    ...
```

- Replace `get_bot_catalog_client` with:

```python
    def get_bot_directory() -> BotDirectory:
        return app.state.bot_directory
```

- Replace the two bot endpoints and the notebook endpoint with:

```python
    @app.get("/bots", response_model=BotListResponse)
    def get_bots(directory: BotDirectory = Depends(get_bot_directory)) -> BotListResponse:
        return list_bot_directory(directory)

    @app.post("/bots/new", response_model=BotCreateResponse)
    def post_new_bot(
        request: BotCreateRequest,
        notebook_launcher: NotebookLauncher = Depends(get_notebook_launcher),
    ) -> BotCreateResponse:
        try:
            return create_bot(notebook_launcher, request.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/bot-connections", response_model=ConnectionCreateResponse)
    def post_bot_connection(
        request: ConnectionCreateRequest,
        repository: MatchRepository = Depends(get_repository),
        directory: BotDirectory = Depends(get_bot_directory),
    ) -> ConnectionCreateResponse:
        try:
            return add_bot_connection(repository, directory, request.url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/bot-connections/{connection_id}")
    def delete_bot_connection(
        connection_id: str,
        repository: MatchRepository = Depends(get_repository),
    ) -> dict:
        try:
            remove_bot_connection(repository, connection_id)
        except ConnectionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"status": "deleted"}

    @app.post("/notebooks/{bot_id}/launch", response_model=NotebookLaunchResponse)
    def post_launch_notebook(
        bot_id: str,
        directory: BotDirectory = Depends(get_bot_directory),
        notebook_launcher: NotebookLauncher = Depends(get_notebook_launcher),
    ) -> NotebookLaunchResponse:
        try:
            return launch_notebook(directory, notebook_launcher, bot_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except BotNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
```

Compatibility note: `ManagedMatchRuntimeManager` still calls `repository.get_bot` at this point (fixed in Task 7); managed-match tests inject their own repository with the old methods still present, so the suite stays green.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run --with pytest pytest quality/tests/test_bot_directory_api.py quality/tests/test_notebook_launch_api.py quality/tests/test_managed_match_api.py quality/tests/test_bot_directory.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add -A services/native-runtime/src/ticket_to_ride/backend quality/tests/test_bot_directory_api.py quality/tests/test_notebook_launch_api.py
git rm quality/tests/test_bot_registry_api.py
git commit -m "feat: live merged /bots listing, /bots/new scaffolding, bot connection endpoints"
```

---

### Task 7: Route managed-match seats through the directory (remote bots playable)

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/backend/runtime/managed_match_runtime.py`
- Modify: `services/native-runtime/src/ticket_to_ride/backend/app.py` (pass the directory to the runtime manager)
- Test: `quality/tests/test_remote_executor_routing.py` (new)
- Test: `quality/tests/test_managed_match_api.py` (modify)

**Interfaces:**
- Consumes: `BotDirectory.resolve`, `DirectoryBot`, `DirectoryListing`; `BotApiExecutor(bot_id, base_url=...)` (already exists in `runtime/executor.py`).
- Produces: `ManagedMatchRuntimeManager(repository, *, executor_factory=None, bot_directory=None)` — default executor factory resolves through the directory: remote bots → `BotApiExecutor(bot_id, base_url=connection url)`; local/unresolvable bots → the existing env-gated `_default_executor_factory`. `_resolve_bot_names` uses the directory instead of `repository.get_bot`.

- [ ] **Step 1: Write the failing tests**

Create `quality/tests/test_remote_executor_routing.py`:

```python
from __future__ import annotations

import unittest

from ticket_to_ride.backend.bot_directory import DirectoryBot, DirectoryListing
from ticket_to_ride.backend.repository import InMemoryMatchRepository
from ticket_to_ride.backend.runtime import ManagedMatchRuntimeManager
from ticket_to_ride.backend.runtime.executor import BotApiExecutor, InProcessBotExecutor


def directory_bot(bot_id: str, *, source: str, base_url: str | None = None) -> DirectoryBot:
    return DirectoryBot(
        bot_id=bot_id,
        name=bot_id.replace("_", " ").title(),
        version="1.0.0",
        description="d",
        author="",
        tags=[],
        source=source,
        connection_id="conn1" if source == "remote" else None,
        base_url=base_url,
        module_path="" if source == "remote" else f"/repo/bots/{bot_id}.py",
    )


class FakeBotDirectory:
    def __init__(self, bots: list[DirectoryBot]) -> None:
        self.bots = list(bots)

    def list_all(self) -> DirectoryListing:
        return DirectoryListing(bots=list(self.bots), connections=[])

    def resolve(self, bot_id: str) -> DirectoryBot:
        for bot in self.bots:
            if bot.bot_id == bot_id:
                return bot
        raise KeyError(f"Unknown bot '{bot_id}'.")


class RemoteExecutorRoutingTests(unittest.TestCase):
    def build_manager(self, bots: list[DirectoryBot]) -> ManagedMatchRuntimeManager:
        return ManagedMatchRuntimeManager(
            InMemoryMatchRepository(),
            bot_directory=FakeBotDirectory(bots),
        )

    def test_remote_bot_routes_to_bot_api_executor_with_connection_url(self) -> None:
        manager = self.build_manager(
            [directory_bot("friend_bot", source="remote", base_url="http://friend-host:8001")]
        )

        executor = manager.executor_factory("friend_bot")

        self.assertIsInstance(executor, BotApiExecutor)
        self.assertEqual(executor.base_url, "http://friend-host:8001")

    def test_local_bot_routes_to_in_process_executor(self) -> None:
        manager = self.build_manager([directory_bot("random_bot", source="local")])

        executor = manager.executor_factory("random_bot")

        self.assertIsInstance(executor, InProcessBotExecutor)

    def test_unresolvable_bot_falls_back_to_in_process_executor(self) -> None:
        manager = self.build_manager([])

        executor = manager.executor_factory("ghost_bot")

        self.assertIsInstance(executor, InProcessBotExecutor)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --with pytest pytest quality/tests/test_remote_executor_routing.py -q`
Expected: FAIL — `__init__() got an unexpected keyword argument 'bot_directory'`.

- [ ] **Step 3: Implement**

In `BACKEND/runtime/managed_match_runtime.py`:
- Add import: `from ticket_to_ride.backend.bot_directory import BotDirectory` and `from ticket_to_ride.backend.bot_catalog import BotCatalogError`.
- Change `__init__`:

```python
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
```

(The unresolvable branch returns the default executor whose `start()` will fail, feeding the existing per-round fallback machinery — matches the spec's offline-remote behavior.)
- Replace `_resolve_bot_names`:

```python
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
```

In `BACKEND/app.py`, update `get_runtime_manager`:

```python
    def get_runtime_manager() -> ManagedMatchRuntimeManager:
        if app.state.runtime_manager is None:
            app.state.runtime_manager = ManagedMatchRuntimeManager(
                app.state.match_repository,
                bot_directory=app.state.bot_directory,
            )
        return app.state.runtime_manager
```

- [ ] **Step 4: Update `test_managed_match_api.py`**

The setUp currently registers bots via `repository.upsert_bot`. Replace that with a fake directory:
- Add imports: `from ticket_to_ride.backend.bot_directory import DirectoryBot, DirectoryListing`.
- Add the same `FakeBotDirectory` class and a helper as in `test_remote_executor_routing.py` (repeat the code — module-level in this test file):

```python
def local_directory_bot(bot_id: str, name: str) -> DirectoryBot:
    return DirectoryBot(
        bot_id=bot_id,
        name=name,
        version="1.0.0",
        description=f"{name} description",
        author="Test",
        tags=[],
        source="local",
        connection_id=None,
        base_url=None,
        module_path=f"/repo/bots/{bot_id}.py",
    )


class FakeBotDirectory:
    def __init__(self, bots: list[DirectoryBot]) -> None:
        self.bots = list(bots)

    def list_all(self) -> DirectoryListing:
        return DirectoryListing(bots=list(self.bots), connections=[])

    def resolve(self, bot_id: str) -> DirectoryBot:
        for bot in self.bots:
            if bot.bot_id == bot_id:
                return bot
        raise KeyError(f"Unknown bot '{bot_id}'.")
```

- Replace the `setUp` body's three `self._register_bot(...)` calls (and delete the `_register_bot` helper method) with:

```python
        self.bot_directory = FakeBotDirectory(
            [
                local_directory_bot("slow_bot", "Slow Bot"),
                local_directory_bot("steady_bot", "Steady Bot"),
                local_directory_bot("random_bot", "Random Bot"),
                local_directory_bot("qualifier_bot", "Qualifier Bot"),
            ]
        )
```

  (Include `qualifier_bot` because a later test registered it separately — check line ~208 and remove that call too.)
- Every `ManagedMatchRuntimeManager(self.repository, executor_factory=factory)` construction gains `bot_directory=self.bot_directory`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --with pytest pytest quality/tests/test_remote_executor_routing.py quality/tests/test_managed_match_api.py quality/tests/test_runtime_failover.py quality/tests/test_runtime_controllers.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/backend/runtime/managed_match_runtime.py services/native-runtime/src/ticket_to_ride/backend/app.py quality/tests/test_remote_executor_routing.py quality/tests/test_managed_match_api.py
git commit -m "feat: managed matches resolve seats via BotDirectory; remote bots playable"
```

---

### Task 8: Retire the persisted bots collection

Nothing reads the old bot records anymore — remove them.

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/backend/repository.py` (remove `upsert_bot`, `list_bots`, `get_bot` from ABC and `InMemoryMatchRepository`, plus `self.bots`)
- Modify: `services/native-runtime/src/ticket_to_ride/backend/pocketbase.py` (remove `upsert_bot`, `list_bots`, `get_bot`, `_normalize_bot`)
- Modify: `services/native-runtime/src/ticket_to_ride/backend/bootstrap_pocketbase.py` (remove the `bots` entry from `COLLECTIONS`; reset tuple becomes `("bot_connections", "managed_rounds", "managed_matches", "turns", "rounds", "matches")`)
- Test: `quality/tests/test_pocketbase_schema.py` (modify)
- Test: `quality/tests/test_pocketbase_repository.py` (modify)

**Interfaces:**
- Produces: `MatchRepository` no longer declares any bot-record methods; PocketBase schema has no `bots` collection. (`ensure_collections` will detect the schema change on next boot and reset project collections — replay/match data is disposable research data, consistent with the existing reset-on-mismatch behavior.)

- [ ] **Step 1: Update tests first**

- `quality/tests/test_pocketbase_schema.py`: remove the `bots`-specific assertions — drop `bots` from expected reset/created name lists (reset expectation becomes `["bot_connections", "managed_rounds", "managed_matches", "turns", "rounds", "matches"]`; created becomes `["matches", "rounds", "turns", "managed_matches", "managed_rounds", "bot_connections"]`), delete the `bots = next(...)` lookups and fake `"bots"` collection dict entries, and update any `invalid` list expectations that mention `"bots"`. Read each failing assertion and mirror the new `COLLECTIONS` content exactly.
- `quality/tests/test_pocketbase_repository.py`: delete `test_list_bots_fetches_all_pages_and_sorts_locally` and `test_upsert_bot_updates_existing_record_by_id`.

- [ ] **Step 2: Run to verify the expected failures**

Run: `uv run --with pytest pytest quality/tests/test_pocketbase_schema.py -q`
Expected: FAIL — schema still contains `bots`.

- [ ] **Step 3: Implement the removals**

Apply the removals listed under **Files** above. Grep to confirm nothing else references them:

```bash
grep -rn "upsert_bot\|repository\.get_bot\|repository\.list_bots" services/ quality/ applications/ integrations/ --include="*.py"
```

Expected: no hits. (Catalog clients and `BotDirectory` keep their own `list_bots`/`resolve` methods — those are different objects and stay; this grep targets only the retired repository methods.)

- [ ] **Step 4: Run the full backend suite**

Run: `uv run --with pytest pytest quality/tests -q -x --ignore=quality/tests/test_random_bot_match_performance.py`
Expected: PASS (performance test excluded for speed; it is unaffected).

- [ ] **Step 5: Commit**

```bash
git add -A services/native-runtime/src/ticket_to_ride/backend quality/tests/test_pocketbase_schema.py quality/tests/test_pocketbase_repository.py
git commit -m "refactor: retire persisted bots collection in favor of live discovery"
```

---

### Task 9: Viewer — auto-loading panel, chooser modal, connection groups

**Files:**
- Modify: `applications/viewer/components/services/bot-registry.jsx` (full rewrite)
- Modify: `applications/viewer/components/dashboard/BotsDashboard.jsx` (full rewrite)
- Modify: `applications/viewer/components/viewer-shell.css` (add classes)
- Modify: `applications/viewer/components/layout/Sidebar.jsx` (nav copy)
- Test: `quality/tests/test_viewer_shell.py` (modify)

**Interfaces:**
- Consumes: `GET /bots` → `{bots: [{botId, name, version, description, author, tags, source, connectionId, baseUrl}], connections: [{connectionId, url, status, error, botCount, createdAt}]}`; `POST /bots/new {name}` → `{botId, url}`; `POST /bot-connections {url}`; `DELETE /bot-connections/{id}`; `POST /notebooks/{botId}/launch`.
- Produces: `bot-registry.jsx` exports `addConnection, createBot, launchNotebook, listBots, removeConnection` (no `registerBot`).

- [ ] **Step 1: Update the shell test first**

In `quality/tests/test_viewer_shell.py`, replace these assertions:

```python
        self.assertIn("Add Bot", bots_dashboard)
        self.assertIn("registerBot", bots_dashboard)
        self.assertIn("random_bot", bots_dashboard)
        self.assertIn("Bot ID", bots_dashboard)
        self.assertIn("listBots", bot_registry_service)
        self.assertIn('fetch(`${apiBase}/bots`)', bot_registry_service)
```

with:

```python
        self.assertIn("Add Bot", bots_dashboard)
        self.assertIn("New Bot", bots_dashboard)
        self.assertIn("Add Connection", bots_dashboard)
        self.assertIn("createBot", bots_dashboard)
        self.assertIn("addConnection", bots_dashboard)
        self.assertIn("removeConnection", bots_dashboard)
        self.assertIn("listBots", bot_registry_service)
        self.assertIn('fetch(`${apiBase}/bots`)', bot_registry_service)
        self.assertIn('fetch(`${apiBase}/bots/new`', bot_registry_service)
        self.assertIn('fetch(`${apiBase}/bot-connections`', bot_registry_service)
```

and replace `self.assertIn("Search and register local bots", sidebar)` with `self.assertIn("Discover local bots and connections", sidebar)`.

Run: `uv run --with pytest pytest quality/tests/test_viewer_shell.py -q` — Expected: FAIL.

- [ ] **Step 2: Rewrite the service layer**

Replace the full contents of `VIEWER/components/services/bot-registry.jsx` with:

```jsx
async function readResponseError(response, fallbackMessage) {
  try {
    const payload = await response.json();
    if (payload?.detail) {
      throw new Error(payload.detail);
    }
  } catch (error) {
    if (error instanceof Error && error.message !== "Unexpected end of JSON input") {
      throw error;
    }
  }

  throw new Error(fallbackMessage);
}

async function listBots(apiBase) {
  const response = await fetch(`${apiBase}/bots`);
  if (!response.ok) {
    return readResponseError(response, `Bot list request failed with status ${response.status}`);
  }

  return response.json();
}

async function createBot(apiBase, name) {
  const response = await fetch(`${apiBase}/bots/new`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ name }),
  });

  if (!response.ok) {
    return readResponseError(response, `Bot creation failed with status ${response.status}`);
  }

  return response.json();
}

async function addConnection(apiBase, url) {
  const response = await fetch(`${apiBase}/bot-connections`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ url }),
  });

  if (!response.ok) {
    return readResponseError(response, `Connection request failed with status ${response.status}`);
  }

  return response.json();
}

async function removeConnection(apiBase, connectionId) {
  const response = await fetch(`${apiBase}/bot-connections/${encodeURIComponent(connectionId)}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    return readResponseError(response, `Connection removal failed with status ${response.status}`);
  }

  return response.json();
}

async function launchNotebook(apiBase, botId) {
  const response = await fetch(`${apiBase}/notebooks/${encodeURIComponent(botId)}/launch`, {
    method: "POST",
  });

  if (!response.ok) {
    return readResponseError(response, `Notebook launch failed with status ${response.status}`);
  }

  return response.json();
}

export {
  addConnection,
  createBot,
  launchNotebook,
  listBots,
  removeConnection,
};
```

- [ ] **Step 3: Rewrite the dashboard**

Replace the full contents of `VIEWER/components/dashboard/BotsDashboard.jsx` with:

```jsx
import { RUN_TRANSITION, h, useDeferredValue, useEffect, useMemo, useState } from "../runtime.jsx";
import { CardShell } from "../atoms/CardShell.jsx";
import { UiIcon } from "../atoms/UiIcon.jsx";
import { addConnection, createBot, launchNotebook, listBots, removeConnection } from "../services/bot-registry.jsx";

function sortBots(bots) {
  return bots
    .slice()
    .sort((left, right) => {
      const nameComparison = left.name.localeCompare(right.name, undefined, { sensitivity: "base" });
      if (nameComparison !== 0) {
        return nameComparison;
      }

      return left.botId.localeCompare(right.botId, undefined, { sensitivity: "base" });
    });
}

function normalizeBot(bot) {
  const sourceLabel = bot.source === "local" ? "Local" : bot.baseUrl || "Remote";
  return {
    ...bot,
    searchText: [bot.botId, bot.name, bot.version, (bot.tags || []).join(" "), bot.source, sourceLabel]
      .join(" ")
      .toLowerCase(),
    sourceLabel,
  };
}

function AddBotModal(props) {
  const [mode, setMode] = useState("choose");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [submitState, setSubmitState] = useState({ kind: "idle", message: "" });
  const isSaving = submitState.kind === "saving";

  useEffect(() => {
    function onKeyDown(event) {
      if (event.key === "Escape" && !isSaving) {
        props.onClose();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [props.onClose, isSaving]);

  async function handleCreate(event) {
    event.preventDefault();

    const trimmedName = name.trim();
    if (!trimmedName) {
      setSubmitState({ kind: "error", message: "Bot name is required." });
      return;
    }

    try {
      setSubmitState({ kind: "saving", message: "" });
      const result = await createBot(props.apiBase, trimmedName);
      window.open(result.url, "_blank", "noopener");
      RUN_TRANSITION(() => {
        props.onChanged();
        props.onClose();
      });
    } catch (error) {
      setSubmitState({
        kind: "error",
        message: error.message || "Unable to create the bot.",
      });
    }
  }

  async function handleConnect(event) {
    event.preventDefault();

    const trimmedUrl = url.trim();
    if (!trimmedUrl) {
      setSubmitState({ kind: "error", message: "Connection URL is required." });
      return;
    }

    try {
      setSubmitState({ kind: "saving", message: "" });
      await addConnection(props.apiBase, trimmedUrl);
      RUN_TRANSITION(() => {
        props.onChanged();
        props.onClose();
      });
    } catch (error) {
      setSubmitState({
        kind: "error",
        message: error.message || "Unable to connect to the bot API.",
      });
    }
  }

  function switchMode(nextMode) {
    setSubmitState({ kind: "idle", message: "" });
    setMode(nextMode);
  }

  const title = mode === "new" ? "New Bot" : mode === "connect" ? "Add Connection" : "Add Bot";
  const subtitle =
    mode === "new"
      ? "Name your bot; a notebook is scaffolded from the template and opened for editing."
      : mode === "connect"
        ? "Point at someone else's bot API base URL, e.g. http://friend-host:8001."
        : "Create a brand-new bot or connect to bots served from another machine.";

  return h(
    "div",
    {
      className: "bots-add-modal-backdrop",
      onClick: isSaving ? undefined : props.onClose,
    },
    h(
      "div",
      {
        className: "bots-add-modal",
        onClick: (event) => event.stopPropagation(),
        role: "dialog",
        "aria-modal": "true",
        "aria-label": title,
      },
      h(
        "div",
        { className: "bots-add-modal-header" },
        h(
          "div",
          null,
          h("p", { className: "shell-eyebrow" }, "Bot Directory"),
          h("h2", { className: "panel-title" }, title),
          h("p", { className: "bots-panel-subtitle" }, subtitle)
        ),
        h(
          "button",
          {
            className: "matches-modal-close",
            type: "button",
            onClick: props.onClose,
            disabled: isSaving,
            "aria-label": "Close add bot modal",
          },
          h(UiIcon, { name: "close" })
        )
      ),
      mode === "choose"
        ? h(
            "div",
            { className: "bots-add-choice-grid" },
            h(
              "button",
              { className: "bots-add-choice", type: "button", onClick: () => switchMode("new") },
              h(UiIcon, { name: "add" }),
              h("span", { className: "bots-add-choice-title" }, "New Bot"),
              h("span", { className: "bots-add-choice-copy" }, "Scaffold a notebook bot from a name.")
            ),
            h(
              "button",
              { className: "bots-add-choice", type: "button", onClick: () => switchMode("connect") },
              h(UiIcon, { name: "link" }),
              h("span", { className: "bots-add-choice-title" }, "Add Connection"),
              h("span", { className: "bots-add-choice-copy" }, "Connect to someone else's bot API by URL.")
            )
          )
        : h(
            "form",
            { className: "bots-add-form", onSubmit: mode === "new" ? handleCreate : handleConnect },
            mode === "new"
              ? h(
                  "label",
                  { className: "matches-modal-field" },
                  h("span", null, "Bot name"),
                  h("input", {
                    type: "text",
                    value: name,
                    placeholder: "My Cool Bot",
                    autoFocus: true,
                    disabled: isSaving,
                    onInput: (event) => setName(event.target.value),
                  })
                )
              : h(
                  "label",
                  { className: "matches-modal-field" },
                  h("span", null, "Bot API URL"),
                  h("input", {
                    type: "url",
                    value: url,
                    placeholder: "http://friend-host:8001",
                    autoFocus: true,
                    disabled: isSaving,
                    onInput: (event) => setUrl(event.target.value),
                  })
                ),
            submitState.kind === "error"
              ? h("p", { className: "bots-add-error" }, submitState.message)
              : null,
            h(
              "div",
              { className: "bots-add-modal-actions" },
              h(
                "button",
                {
                  className: "matches-modal-reset",
                  type: "button",
                  onClick: () => switchMode("choose"),
                  disabled: isSaving,
                },
                "Back"
              ),
              h(
                "button",
                {
                  className: "matches-modal-link bots-panel-add",
                  type: "submit",
                  disabled: isSaving,
                },
                isSaving
                  ? mode === "new"
                    ? "Creating..."
                    : "Connecting..."
                  : mode === "new"
                    ? "Create Bot"
                    : "Connect"
              )
            )
          )
    )
  );
}

function BotCard(props) {
  const bot = props.bot;
  return h(
    "article",
    { key: bot.botId, className: "bots-card" },
    h(
      "div",
      { className: "bots-card-top" },
      h(
        "div",
        { className: "bots-card-copy" },
        h("h3", null, bot.name),
        h("p", { className: "bots-card-path" }, bot.sourceLabel)
      ),
      h(
        "span",
        { className: "matches-modal-status" },
        bot.source === "local" ? "Local" : "Remote"
      )
    ),
    h(
      "div",
      { className: "matches-modal-card-meta" },
      h("span", { className: "matches-modal-meta-pill" }, bot.botId),
      h("span", { className: "matches-modal-meta-pill" }, bot.version),
      (bot.tags || []).map((tag) => h("span", { key: tag, className: "matches-modal-meta-pill" }, tag))
    ),
    bot.source === "local"
      ? h(
          "div",
          { className: "bots-card-actions" },
          h(
            "button",
            {
              className: "matches-modal-link",
              type: "button",
              disabled: props.launchState === "opening",
              onClick: () => props.onOpenNotebook(bot),
            },
            props.launchState === "opening" ? "Opening..." : "Open Notebook"
          ),
          props.launchState === "error"
            ? h("span", { className: "bots-add-error" }, "Unable to open the notebook.")
            : null
        )
      : null
  );
}

function BotsDashboard(props) {
  const [directory, setDirectory] = useState({ bots: [], connections: [] });
  const [query, setQuery] = useState("");
  const [fetchState, setFetchState] = useState({ kind: "loading", message: "" });
  const [isAddBotOpen, setAddBotOpen] = useState(false);
  const [launchState, setLaunchState] = useState({});
  const [pendingRemoveId, setPendingRemoveId] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);
  const deferredQuery = useDeferredValue(query);

  useEffect(() => {
    let isCancelled = false;

    async function loadDirectory() {
      try {
        setFetchState({ kind: "loading", message: "" });
        const payload = await listBots(props.apiBase);
        if (isCancelled) {
          return;
        }

        setDirectory({
          bots: Array.isArray(payload?.bots) ? payload.bots : [],
          connections: Array.isArray(payload?.connections) ? payload.connections : [],
        });
        setFetchState({ kind: "ready", message: "" });
      } catch (error) {
        if (!isCancelled) {
          setFetchState({
            kind: "error",
            message: error.message || "Unable to load the bot directory.",
          });
        }
      }
    }

    loadDirectory();
    return () => {
      isCancelled = true;
    };
  }, [props.apiBase, reloadToken]);

  function refresh() {
    setReloadToken((token) => token + 1);
  }

  const normalizedBots = useMemo(() => sortBots(directory.bots).map(normalizeBot), [directory.bots]);
  const filteredBots = useMemo(() => {
    const normalizedQuery = deferredQuery.trim().toLowerCase();
    if (!normalizedQuery) {
      return normalizedBots;
    }

    return normalizedBots.filter((bot) => bot.searchText.includes(normalizedQuery));
  }, [deferredQuery, normalizedBots]);

  const localBots = filteredBots.filter((bot) => bot.source === "local");

  async function handleOpenNotebook(bot) {
    setLaunchState((current) => ({ ...current, [bot.botId]: "opening" }));
    try {
      const result = await launchNotebook(props.apiBase, bot.botId);
      window.open(result.url, "_blank", "noopener");
      setLaunchState((current) => ({ ...current, [bot.botId]: "idle" }));
    } catch (error) {
      setLaunchState((current) => ({ ...current, [bot.botId]: "error" }));
    }
  }

  async function handleRemoveConnection(connection) {
    if (pendingRemoveId !== connection.connectionId) {
      setPendingRemoveId(connection.connectionId);
      return;
    }

    try {
      await removeConnection(props.apiBase, connection.connectionId);
      setPendingRemoveId(null);
      refresh();
    } catch (error) {
      setPendingRemoveId(null);
      setFetchState({ kind: "error", message: error.message || "Unable to remove the connection." });
    }
  }

  function renderConnectionGroup(connection) {
    const connectionBots = filteredBots.filter((bot) => bot.connectionId === connection.connectionId);
    return h(
      "div",
      { key: connection.connectionId, className: "bots-group" },
      h(
        "div",
        { className: "bots-group-header" },
        h(
          "div",
          { className: "bots-group-title" },
          h("h3", null, connection.url),
          h(
            "span",
            {
              className:
                connection.status === "online"
                  ? "bots-status-pill"
                  : "bots-status-pill bots-status-pill--offline",
            },
            connection.status === "online" ? "Online" : "Offline"
          )
        ),
        h(
          "button",
          {
            className: "matches-modal-reset bots-connection-remove",
            type: "button",
            onClick: () => handleRemoveConnection(connection),
          },
          pendingRemoveId === connection.connectionId ? "Confirm remove" : "Remove"
        )
      ),
      connection.status === "offline"
        ? h("div", { className: "bots-empty" }, connection.error || "This connection is unreachable.")
        : !connectionBots.length
          ? h("div", { className: "bots-empty" }, "No bots match on this connection.")
          : connectionBots.map((bot) =>
              h(BotCard, {
                key: bot.botId,
                bot,
                launchState: launchState[bot.botId],
                onOpenNotebook: handleOpenNotebook,
              })
            )
    );
  }

  return h(
    "div",
    { className: "bots-dashboard-grid" },
    h(
      "section",
      { className: "bots-grid-slot-list" },
      h(
        CardShell,
        { className: "bots-panel bots-panel--registry" },
        h(
          "div",
          { className: "panel-header bots-panel-header" },
          h(
            "div",
            null,
            h("p", { className: "shell-eyebrow" }, "Bot Directory"),
            h("h2", { className: "panel-title" }, "Bots"),
            h("p", { className: "bots-panel-subtitle" }, props.apiBase)
          ),
          h(
            "button",
            {
              className: "matches-modal-link bots-panel-add",
              type: "button",
              onClick: () => setAddBotOpen(true),
            },
            h(UiIcon, { name: "add" }),
            h("span", null, "Add Bot")
          )
        ),
        h(
          "div",
          { className: "bots-toolbar" },
          h(
            "label",
            { className: "matches-modal-field bots-toolbar-search" },
            h("span", null, "Search"),
            h("input", {
              type: "search",
              value: query,
              placeholder: "Search by bot ID, name, tag, or source",
              onInput: (event) => setQuery(event.target.value),
            })
          )
        ),
        h(
          "p",
          { className: "bots-summary" },
          fetchState.kind === "loading"
            ? "Discovering bots..."
            : fetchState.kind === "error"
              ? fetchState.message
              : `${filteredBots.length} of ${normalizedBots.length} bots shown`
        ),
        h(
          "div",
          { className: "bots-list" },
          fetchState.kind === "loading"
            ? h("div", { className: "bots-empty" }, "Scanning local bots and connections.")
            : fetchState.kind === "error"
              ? h("div", { className: "bots-empty" }, fetchState.message)
              : [
                  h(
                    "div",
                    { key: "local", className: "bots-group" },
                    h(
                      "div",
                      { className: "bots-group-header" },
                      h(
                        "div",
                        { className: "bots-group-title" },
                        h("h3", null, "Local Bots"),
                        h("span", { className: "bots-status-pill" }, String(localBots.length))
                      )
                    ),
                    !localBots.length
                      ? h(
                          "div",
                          { className: "bots-empty" },
                          "No local bots discovered. Create one with Add Bot, or drop a notebook into integrations/external/bots/."
                        )
                      : localBots.map((bot) =>
                          h(BotCard, {
                            key: bot.botId,
                            bot,
                            launchState: launchState[bot.botId],
                            onOpenNotebook: handleOpenNotebook,
                          })
                        )
                  ),
                  directory.connections.map(renderConnectionGroup),
                ]
        )
      )
    ),
    h("section", { className: "bots-grid-slot-empty-top" }, h(CardShell, { className: "bots-panel bots-panel--empty" })),
    h("section", { className: "bots-grid-slot-empty-bottom" }, h(CardShell, { className: "bots-panel bots-panel--empty" })),
    isAddBotOpen
      ? h(AddBotModal, {
          apiBase: props.apiBase,
          onClose: () => setAddBotOpen(false),
          onChanged: refresh,
        })
      : null
  );
}

export { BotsDashboard };
```

Note: `UiIcon` renders Material Symbols by name — `"link"` is a valid Material Symbols name, same mechanism as the existing `"add"`/`"close"` (verify `UiIcon.jsx` maps names straight through; if it has an allowlist, add `link`).

- [ ] **Step 4: Add CSS**

In `VIEWER/components/viewer-shell.css`, insert after the `.bots-add-error` rule (~line 610):

```css
.bots-add-choice-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.bots-add-choice {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding: 16px;
  border: 1px solid var(--shell-border);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.03);
  color: inherit;
  cursor: pointer;
  text-align: left;
}

.bots-add-choice:hover {
  border-color: rgba(255, 92, 52, 0.6);
}

.bots-add-choice-title {
  font-weight: 600;
}

.bots-add-choice-copy {
  font-size: 0.85em;
  opacity: 0.75;
}

.bots-group {
  display: grid;
  gap: 10px;
}

.bots-group + .bots-group {
  margin-top: 16px;
}

.bots-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.bots-group-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.bots-group-title h3 {
  margin: 0;
  font-size: 0.95em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bots-status-pill {
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid rgba(112, 224, 152, 0.5);
  color: #70e098;
  font-size: 0.75em;
}

.bots-status-pill--offline {
  border-color: rgba(255, 120, 120, 0.5);
  color: #ff9c9c;
}

.bots-connection-remove {
  flex-shrink: 0;
}
```

- [ ] **Step 5: Update the sidebar copy**

In `VIEWER/components/layout/Sidebar.jsx`, change the bots nav description string `"Search and register local bots"` to `"Discover local bots and connections"`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --with pytest pytest quality/tests/test_viewer_shell.py quality/tests/test_viewer_vite_config.py -q`
Expected: PASS.

- [ ] **Step 7: Smoke-test against the real backend**

```bash
uv run python - <<'EOF'
from fastapi.testclient import TestClient
from ticket_to_ride.backend.app import create_app
from ticket_to_ride.backend.repository import InMemoryMatchRepository

client = TestClient(create_app(repository=InMemoryMatchRepository()))
payload = client.get("/bots").json()
print("bots:", [bot["botId"] for bot in payload["bots"]])
print("connections:", payload["connections"])
assert any(bot["botId"] == "random_bot" for bot in payload["bots"])
assert all(bot["source"] == "local" for bot in payload["bots"])
EOF
```

Expected: prints the real local bots (`random_bot`, `example_bot`, `xg_bot`, …) with no registration step.

- [ ] **Step 8: Commit**

```bash
git add applications/viewer/components/services/bot-registry.jsx applications/viewer/components/dashboard/BotsDashboard.jsx applications/viewer/components/viewer-shell.css applications/viewer/components/layout/Sidebar.jsx quality/tests/test_viewer_shell.py
git commit -m "feat: bots panel auto-discovers bots; chooser modal for new bot / add connection"
```

---

### Task 10: Full verification pass

**Files:** none new — fixes only if the suite finds integration gaps.

- [ ] **Step 1: Run the full test suite**

Run: `uv run --with pytest pytest quality/tests integrations/external/tests -q`
Expected: all PASS. Fix any failures before proceeding (report unexpected ones rather than papering over them).

- [ ] **Step 2: End-to-end scaffold check (real template, temp cleanup)**

```bash
uv run python - <<'EOF'
from pathlib import Path
from ticket_to_ride.backend.bot_scaffold import scaffold_bot

scaffolded = scaffold_bot("Plan Smoke Bot")
path = Path(scaffolded.path)
try:
    source = path.read_text(encoding="utf-8")
    assert '"id": "plan_smoke_bot"' in source
    assert "class PlanSmokeBot(ActionBot):" in source
    print("scaffold OK:", scaffolded)
finally:
    path.unlink()
EOF
```

Expected: `scaffold OK: ScaffoldedBot(bot_id='plan_smoke_bot', ...)` and the file is removed afterward.

- [ ] **Step 3: Verify the live app if the backend can run locally**

Use the `verify` skill if available in-session; at minimum re-run the Task 9 Step 7 smoke script.

- [ ] **Step 4: Final commit (if fixes were made)**

```bash
git add -A
git commit -m "fix: integration fixes from full-suite verification of bots panel rework"
```
