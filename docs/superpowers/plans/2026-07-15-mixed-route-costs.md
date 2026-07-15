# Mixed Route Costs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Routes cost an ordered list of components (`3U+2R`, `2(G|B)+2X`, `2L+3U`) instead of one color; the engine enumerates every legal payment, bots choose among them, and the board renders per-segment colors (split triangles for either-or, rainbow gradient for locomotives).

**Architecture:** One canonical `CostComponent` model in a new `engine/state/costs.py`; classic routes are the one-component case synthesized at load (no mixed-vs-classic branch anywhere). The hot enumeration core in `actions.py` keeps its current single-color loop verbatim as the fast path (byte-for-byte parity on existing maps) and adds a general payment enumerator for everything else. Display precomputes per-rectangle render specs Python-side (`data.segments`); the three renderers (canvas, CSS, SVG pie) each materialize a shared rainbow-gradient-stops config for locomotives.

**Tech Stack:** Python 3 (uv-managed), `unittest` (pytest is NOT installed), esbuild-bundled vanilla-JS anywidget widgets (force-graph canvas).

**Spec:** `docs/superpowers/specs/2026-07-15-mixed-route-costs-design.md`

## Global Constraints

- Run tests with `uv run python -m unittest discover -s quality/tests -p "<pattern>"` — never pytest (not installed). Run scripts with `uv run python`.
- **Byte-for-byte parity on existing maps** is the acceptance bar for every engine task: `AffordabilityParityTests` in `quality/tests/test_engine_caching.py` must pass unchanged, and the Task 1 parity dump must `cmp` clean at the end.
- Card letters: `R B U G O P W Y` real colors, `X` grey (any uniform color), `L` locomotive (wild). `B` is **black**, `U` is blue.
- Payment semantics (from spec): uniform color per component, components choose independently, locomotives substitute anywhere, an `L` component is a locomotive floor for the whole payment.
- Load-time guards: counts sum to length; distinct real colors mentioned ≤ length; `X` and `L` never inside multi-option sets; option letters distinct, real.
- Single-component actions keep `payment=None`; serialized records may gain `payment: null`, and the stored database may be rebuilt.
- Execution trusts actions selected from the engine-produced legal menu; it does not revalidate payment structure in `Player.__apply_claim`.
- Mixed-map bot scope is Qualifier, Example, and Random. Fable and Codex Best are deferred.
- The working tree contains unrelated user changes (xG files, pyproject, uv.lock). `git add` only the files each task names — never `git add -A`.
- After any change under `applications/notebook_harness/widget-src/src/`, rebuild bundles: `cd applications/notebook_harness/widget-src && npm run build` (outputs to `../static/`), and commit the regenerated static files with the source.
- Scratchpad for throwaway artifacts: `/private/tmp/claude-501/-Users-lucasstarkey-Documents-GitHub-ticket-to-ride/5faacd7e-5a8e-4ee3-ae3a-99dfc5744089/scratchpad` (call it `$SCRATCH` below; it is session-scoped, so Task 1's baseline must be regenerated if the session changes).

---

### Task 1: Baseline parity artifacts

**Files:**
- Create: `$SCRATCH/parity_mixed_before.json` (scratchpad artifact, not committed)

**Interfaces:**
- Produces: the pre-change behavior fingerprint that Task 9 `cmp`s against.

- [ ] **Step 1: Confirm the tree is at the intended baseline**

Run: `git status --short -- services/native-runtime quality/tests`
Expected: only the pre-existing modifications listed in the conversation baseline (actions.py, map.py, views.py from the caching round) — no partial mixed-cost work.

- [ ] **Step 2: Dump the baseline parity fingerprint**

Run:
```bash
cd /Users/lucasstarkey/Documents/GitHub/ticket_to_ride
uv run python operations/research/profile_engine.py --parity-dump "$SCRATCH/parity_mixed_before.json"
```
Expected: JSON written; script prints per-game seeds/scores summary.

- [ ] **Step 3: Record baseline wall time**

Run: `uv run python operations/research/profile_engine.py 2>&1 | tail -5`
Expected: ~0.38 s/game average. Note the number for Task 9. No commit for this task.

---

### Task 2: Cost model module (`costs.py`)

**Files:**
- Create: `services/native-runtime/src/ticket_to_ride/engine/state/costs.py`
- Test: `quality/tests/test_route_costs.py`

**Interfaces:**
- Produces (all importable from `ticket_to_ride.engine.state.costs`):
  - `CARD_COLORS: Tuple[str, ...]` = `("R", "B", "U", "G", "O", "P", "W", "Y")`
  - `GREY = "X"`, `LOCOMOTIVE = "L"`
  - `class CostError(ValueError)`
  - `@dataclass(frozen=True) CostComponent(count: int, options: Tuple[str, ...])` with methods `is_grey() -> bool`, `is_locomotive() -> bool`, `concrete_options() -> Tuple[str, ...]`
  - `parse_cost(spec: str, length: int) -> Tuple[CostComponent, ...]`
  - `synthesize_cost(length: int, color: str) -> Tuple[CostComponent, ...]`
  - `cost_to_str(cost: Tuple[CostComponent, ...]) -> str`

- [ ] **Step 1: Write the failing tests**

Create `quality/tests/test_route_costs.py`:

```python
"""Cost grammar, validation guards, and component semantics."""
import unittest

from ticket_to_ride.engine.state.costs import (
    CARD_COLORS, CostComponent, CostError, cost_to_str, parse_cost,
    synthesize_cost,
)


class ParseCostTests(unittest.TestCase):
    def test_single_color_term(self):
        self.assertEqual(parse_cost("3U", 3), (CostComponent(3, ("U",)),))

    def test_mixed_terms(self):
        self.assertEqual(
            parse_cost("3U+2R", 5),
            (CostComponent(3, ("U",)), CostComponent(2, ("R",))),
        )

    def test_option_set_preserves_declared_order(self):
        self.assertEqual(parse_cost("2(G|B)", 2), (CostComponent(2, ("G", "B")),))
        self.assertEqual(parse_cost("2(B|G)", 2), (CostComponent(2, ("B", "G")),))

    def test_grey_and_loco_terms(self):
        self.assertEqual(
            parse_cost("3X+2G", 5),
            (CostComponent(3, ("X",)), CostComponent(2, ("G",))),
        )
        self.assertEqual(
            parse_cost("2L+3U", 5),
            (CostComponent(2, ("L",)), CostComponent(3, ("U",))),
        )
        self.assertEqual(parse_cost("3L", 3), (CostComponent(3, ("L",)),))

    def test_whitespace_tolerated(self):
        self.assertEqual(parse_cost(" 3U + 2R ", 5), parse_cost("3U+2R", 5))

    def test_three_option_set(self):
        self.assertEqual(
            parse_cost("2(G|U|R)", 2), (CostComponent(2, ("G", "U", "R")),)
        )


class ValidationGuardTests(unittest.TestCase):
    def test_counts_must_sum_to_length(self):
        with self.assertRaises(CostError):
            parse_cost("3U+2R", 6)

    def test_grey_inside_set_rejected(self):
        with self.assertRaises(CostError):
            parse_cost("3(X|U)", 3)

    def test_loco_inside_set_rejected(self):
        with self.assertRaises(CostError):
            parse_cost("2(L|U)", 2)

    def test_duplicate_option_rejected(self):
        with self.assertRaises(CostError):
            parse_cost("2(G|G)", 2)

    def test_unknown_letter_rejected(self):
        with self.assertRaises(CostError):
            parse_cost("3Q", 3)

    def test_distinct_colors_capped_by_length(self):
        # mentions U, R, Y, G, B = 5 distinct colors on a length-4 route
        with self.assertRaises(CostError):
            parse_cost("1U+1R+1Y+1(G|B)", 4)
        # exactly at the cap is fine
        parse_cost("1U+1R+1Y+1(R|B)", 4)

    def test_garbage_rejected(self):
        for bad in ("", "U3", "3", "(G|B)", "3U+", "3u"):
            with self.assertRaises(CostError, msg=bad):
                parse_cost(bad, 3)

    def test_zero_count_rejected(self):
        with self.assertRaises(CostError):
            parse_cost("0U+3R", 3)


class ComponentSemanticsTests(unittest.TestCase):
    def test_synthesize_matches_classic_routes(self):
        self.assertEqual(synthesize_cost(4, "R"), (CostComponent(4, ("R",)),))
        self.assertEqual(synthesize_cost(3, "X"), (CostComponent(3, ("X",)),))

    def test_concrete_options_opens_grey(self):
        self.assertEqual(CostComponent(3, ("X",)).concrete_options(), CARD_COLORS)
        self.assertEqual(CostComponent(3, ("G", "B")).concrete_options(), ("G", "B"))

    def test_predicates(self):
        self.assertTrue(CostComponent(2, ("X",)).is_grey())
        self.assertTrue(CostComponent(2, ("L",)).is_locomotive())
        self.assertFalse(CostComponent(2, ("G", "B")).is_grey())

    def test_cost_to_str_round_trips(self):
        for spec, length in (("3U+2R", 5), ("2(G|B)+2X", 4), ("2L+3U", 5)):
            self.assertEqual(cost_to_str(parse_cost(spec, length)), spec)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest discover -s quality/tests -p "test_route_costs.py" -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ticket_to_ride.engine.state.costs'`

- [ ] **Step 3: Implement the module**

Create `services/native-runtime/src/ticket_to_ride/engine/state/costs.py`:

```python
"""Route cost components: the mixed-cost payment model.

A route's cost is an ordered tuple of components. Each component is paid in
one uniform color chosen from its options; components choose independently;
locomotives substitute for any card anywhere; an "L" component is a
locomotive floor for the whole payment. A classic single-color route is
simply the one-component case (synthesize_cost), so nothing downstream
branches on mixed-vs-classic.
"""
import re
from dataclasses import dataclass
from typing import Tuple

CARD_COLORS: Tuple[str, ...] = ("R", "B", "U", "G", "O", "P", "W", "Y")
GREY = "X"
LOCOMOTIVE = "L"


class CostError(ValueError):
    """A cost expression violating the grammar or the model's guards."""


@dataclass(frozen=True)
class CostComponent:
    count: int
    options: Tuple[str, ...]

    def is_grey(self) -> bool:
        return self.options == (GREY,)

    def is_locomotive(self) -> bool:
        return self.options == (LOCOMOTIVE,)

    def concrete_options(self) -> Tuple[str, ...]:
        """Colors that may pay this component (grey opens all of them)."""
        return CARD_COLORS if self.is_grey() else self.options


# <count><letter>  or  <count>(<letter>|<letter>[|...]>)
_TERM_RE = re.compile(r"(\d+)(?:([A-Z])|\(([A-Z](?:\|[A-Z])+)\))")


def parse_cost(spec: str, length: int) -> Tuple[CostComponent, ...]:
    """Parse a Cost cell like "3U+2R", "2(G|B)+2X", or "2L+3U"."""
    components = []
    for term in spec.replace(" ", "").split("+"):
        match = _TERM_RE.fullmatch(term)
        if not match:
            raise CostError(f"unparseable cost term {term!r} in {spec!r}")
        count = int(match.group(1))
        if match.group(2):
            options: Tuple[str, ...] = (match.group(2),)
        else:
            options = tuple(match.group(3).split("|"))
        components.append(CostComponent(count, options))
    cost = tuple(components)
    validate_cost(cost, length, spec)
    return cost


def synthesize_cost(length: int, color: str) -> Tuple[CostComponent, ...]:
    """The classic single-color (or grey) route as a one-component cost."""
    return (CostComponent(length, (color,)),)


def validate_cost(cost: Tuple[CostComponent, ...], length: int, spec: str) -> None:
    if not cost:
        raise CostError(f"empty cost {spec!r}")
    for component in cost:
        if component.count <= 0:
            raise CostError(f"non-positive count in {spec!r}")
        options = component.options
        if options in ((GREY,), (LOCOMOTIVE,)):
            continue
        if len(options) != len(set(options)):
            raise CostError(f"duplicate option letter in {spec!r}")
        bad = [letter for letter in options if letter not in CARD_COLORS]
        if bad:
            # covers unknown letters AND X/L inside multi-option sets:
            # X-in-a-set is "basically just grey" (declare X), L is already
            # wild so (L|...) is meaningless.
            raise CostError(f"invalid option letter(s) {bad} in {spec!r}")
    total = sum(component.count for component in cost)
    if total != length:
        raise CostError(f"cost {spec!r} totals {total}, route length is {length}")
    distinct = {
        letter
        for component in cost
        if not (component.is_grey() or component.is_locomotive())
        for letter in component.options
    }
    if len(distinct) > length:
        raise CostError(
            f"cost {spec!r} names {len(distinct)} distinct colors on a "
            f"length-{length} route"
        )


def cost_to_str(cost: Tuple[CostComponent, ...]) -> str:
    """Canonical text form, the inverse of parse_cost."""
    terms = []
    for component in cost:
        if len(component.options) == 1:
            terms.append(f"{component.count}{component.options[0]}")
        else:
            terms.append(f"{component.count}({'|'.join(component.options)})")
    return "+".join(terms)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest discover -s quality/tests -p "test_route_costs.py" -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/engine/state/costs.py quality/tests/test_route_costs.py
git commit -m "feat(engine): CostComponent model with cost grammar and guards"
```

---

### Task 3: Route.cost, CSV `Cost` column, direct-path map loading

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/engine/state/map.py` (Route `__init__` ~line 35, `resolve_map_path` ~line 18, `_load_routes_from_csv` ~line 283)
- Test: `quality/tests/test_route_costs.py` (extend)

**Interfaces:**
- Consumes: Task 2's `parse_cost`, `synthesize_cost`, `cost_to_str`, `CostError`, `CostComponent`.
- Produces:
  - `Route.cost: Tuple[CostComponent, ...]` — always present, one component for classic routes.
  - `Route.color` — unchanged for classic routes; `None` when the cost is not a single fixed/grey letter.
  - `Route.payment_colors() -> frozenset[str]` — union of concrete options across non-locomotive components.
  - `resolve_map_path` accepts an existing `.csv` path directly (tests build maps in temp dirs).
  - CSV column `Cost` (optional) parsed per row; `CostError` re-raised naming the file and city pair.

- [ ] **Step 1: Write the failing tests**

Append to `quality/tests/test_route_costs.py`:

```python
import csv
import tempfile
import unittest
from pathlib import Path

from ticket_to_ride.engine.state.map import MapGraph, Route, resolve_map_path


def write_map_csv(rows, header=("city1", "city2", "Distance", "Color", "Cost")):
    """Write a throwaway map CSV; returns its path (caller's tempdir owns it)."""
    tmpdir = tempfile.mkdtemp()
    path = Path(tmpdir) / "mixed_test.csv"
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


MIXED_ROWS = [
    ("Ax", "Bx", "5", "X", "3U+2R"),
    ("Bx", "Cx", "4", "X", "2(G|B)+2X"),
    ("Cx", "Dx", "3", "X", "3L"),
    ("Ax", "Dx", "5", "X", "2L+3U"),
    ("Ax", "Cx", "2", "R", ""),  # classic row, Cost blank
]


class RouteCostWiringTests(unittest.TestCase):
    def test_classic_construction_synthesizes_cost(self):
        route = Route("A", "B", 4, "R", "A-B-1")
        self.assertEqual(route.cost, (CostComponent(4, ("R",)),))
        self.assertEqual(route.color, "R")
        self.assertEqual(route.payment_colors(), frozenset({"R"}))

    def test_grey_route_opens_all_colors(self):
        route = Route("A", "B", 3, "X", "A-B-1")
        self.assertEqual(route.payment_colors(), frozenset(CARD_COLORS))

    def test_mixed_cost_route_has_no_single_color(self):
        cost = parse_cost("3U+2R", 5)
        route = Route("A", "B", 5, "X", "A-B-1", cost=cost)
        self.assertIsNone(route.color)
        self.assertEqual(route.cost, cost)
        self.assertEqual(route.payment_colors(), frozenset({"U", "R"}))
        self.assertIn("3U+2R", route.route_label)

    def test_pure_locomotive_route_has_no_payment_colors(self):
        route = Route("A", "B", 3, "X", "A-B-1", cost=parse_cost("3L", 3))
        self.assertEqual(route.payment_colors(), frozenset())


class LoaderCostTests(unittest.TestCase):
    def test_loader_parses_cost_column(self):
        path = write_map_csv(MIXED_ROWS)
        graph = MapGraph(player_count=2, map_name=str(path))
        by_pair = {(r.city1, r.city2): r for r in graph.routes}
        self.assertEqual(cost_to_str(by_pair[("Ax", "Bx")].cost), "3U+2R")
        self.assertEqual(cost_to_str(by_pair[("Bx", "Cx")].cost), "2(G|B)+2X")
        self.assertEqual(cost_to_str(by_pair[("Cx", "Dx")].cost), "3L")
        # blank Cost cell falls back to Distance+Color synthesis
        classic = by_pair[("Ax", "Cx")]
        self.assertEqual(classic.color, "R")
        self.assertEqual(classic.cost, (CostComponent(2, ("R",)),))

    def test_loader_error_names_the_row(self):
        path = write_map_csv([("Ax", "Bx", "5", "X", "3U+9R")])
        with self.assertRaisesRegex(CostError, "Ax-Bx"):
            MapGraph(player_count=2, map_name=str(path))

    def test_maps_without_cost_column_load_unchanged(self):
        graph = MapGraph(player_count=2, map_name="classic")
        for route in graph.routes:
            self.assertEqual(len(route.cost), 1)
            self.assertEqual(route.cost[0].options, (route.color,))

    def test_resolve_map_path_accepts_direct_csv(self):
        path = write_map_csv(MIXED_ROWS)
        self.assertEqual(resolve_map_path(str(path)), path)
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run python -m unittest discover -s quality/tests -p "test_route_costs.py" -v`
Expected: new tests FAIL (`unexpected keyword argument 'cost'`, direct path raises ValueError); Task 2's tests still pass.

- [ ] **Step 3: Implement**

In `services/native-runtime/src/ticket_to_ride/engine/state/map.py`:

Add to the imports block:

```python
from ticket_to_ride.engine.state.costs import (
    CostComponent, CostError, cost_to_str, parse_cost, synthesize_cost,
)
```

Extend `resolve_map_path`:

```python
def resolve_map_path(map_name: Optional[str]) -> Path:
    """Resolve a map name to its CSV path, defaulting to the classic map.

    An existing .csv path is returned as-is, so tests and tools can load
    maps from anywhere without staging them into the maps directory.
    """
    resolved_name = map_name or DEFAULT_MAP_NAME
    direct = Path(resolved_name)
    if direct.suffix == ".csv" and direct.exists():
        return direct
    map_path = MAPS_DIR / f"{resolved_name}.csv"
    if not map_path.exists():
        raise ValueError(f"Unknown map '{resolved_name}'. Available maps: {available_maps()}")
    return map_path
```

Extend `Route.__init__` (keep the existing body; changed/added lines shown in context):

```python
    def __init__(self, city1: str, city2: str, length: int, color: str, route_id: str,
                 locomotives: int = 0, is_tunnel: bool = False,
                 cost: 'Optional[Tuple[CostComponent, ...]]' = None):
        """Represent a single route on the map.

        `cost` is the mixed-cost component tuple; omitted, it is synthesized
        from `color` so a classic route is the one-component case. `color`
        stays the single letter for one-component single-option costs and is
        None otherwise (consumers that can meet mixed routes read `cost` /
        `payment_colors()` instead). `locomotives` (legacy ferry minimum)
        and `is_tunnel` are carried from the map data but not yet enforced.
        """
        self.city1 = city1
        self.city2 = city2
        self.length = length
        self.cost = cost if cost is not None else synthesize_cost(length, color)
        if cost is not None:
            color = (cost[0].options[0]
                     if len(cost) == 1 and len(cost[0].options) == 1 and not cost[0].is_locomotive()
                     else None)
        self.color = color
        self._payment_colors = frozenset(
            letter
            for component in self.cost
            if not component.is_locomotive()
            for letter in component.concrete_options()
        )
        self.route_id = route_id
        self.locomotives = locomotives
        self.is_tunnel = is_tunnel
        self.route_label = (
            f"{self.city1.replace(' ', '_')}-{self.city2.replace(' ', '_')}-"
            f"{self.color or cost_to_str(self.cost)}"
        )
        self.claimed_by = None
        # Cities and length never change after load; cache the group key so
        # hot-loop claimability checks don't re-sort it on every call.
        self._sibling_group_key = (tuple(sorted((city1, city2))), length)
```

Also update the class-level annotation `color: str` to `color: 'str | None'` and add `cost: 'Tuple[CostComponent, ...]'`.

Add the accessor method to `Route`:

```python
    def payment_colors(self) -> 'frozenset[str]':
        """Every color that could pay some component (grey opens all 8);
        locomotive components contribute nothing. Bots use this where they
        used to branch on `color == "X"`."""
        return self._payment_colors
```

In `_load_routes_from_csv`, inside the row loop (after `is_tunnel = ...`):

```python
                cost_spec = (row.get("Cost") or "").strip()
                cost = None
                if cost_spec:
                    try:
                        cost = parse_cost(cost_spec, length)
                    except CostError as error:
                        raise CostError(
                            f"{Path(csv_path).name}: {city1}-{city2}: {error}"
                        ) from error
```

and pass it through:

```python
                route = Route(city1, city2, length, color, route_id,
                              locomotives=locomotives, is_tunnel=is_tunnel,
                              cost=cost)
```

Update the docstring of `_load_routes_from_csv` to mention the optional `Cost` column and its grammar.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest discover -s quality/tests -p "test_route_costs.py" -v`
Expected: all PASS.

- [ ] **Step 5: Run the whole suite (parity gate)**

Run: `uv run python -m unittest discover -s quality/tests 2>&1 | tail -3`
Expected: all tests OK (264 + the new ones).

- [ ] **Step 6: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/engine/state/map.py quality/tests/test_route_costs.py
git commit -m "feat(engine): Route.cost wiring, CSV Cost column, direct-path map loading"
```

---

### Task 4: ClaimRoute.payment, claim_spend, payment execution

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/engine/actions.py` (ClaimRoute ~line 39)
- Modify: `services/native-runtime/src/ticket_to_ride/engine/player.py` (`__apply_claim` ~line 116)
- Test: `quality/tests/test_claim_payment.py`

**Interfaces:**
- Consumes: `Route.cost` (Task 3), `write_map_csv`/`MIXED_ROWS` pattern from Task 3's tests.
- Produces:
  - `ClaimRoute(route_id, color, locomotives, payment=None)` — `payment: Optional[Tuple[Tuple[str, int], ...]]`, one `(chosen_color, locomotives_substituted)` pair per cost component in cost order; locomotive components appear as `("L", count)`.
  - `claim_spend(action: ClaimRoute, route: Route) -> Counter[str]` in `actions.py` — the bot valuation hook; exact cards burned.
  - `Player.__apply_claim` executes via `claim_spend` (identical discard order to today for `payment=None`).

- [ ] **Step 1: Write the failing tests**

Create `quality/tests/test_claim_payment.py`:

```python
"""ClaimRoute.payment execution and the claim_spend valuation hook."""
import unittest
from collections import Counter

from ticket_to_ride.engine.actions import ClaimRoute, claim_spend
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.costs import parse_cost
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.map import MapGraph, Route

from quality.tests.test_route_costs import MIXED_ROWS, write_map_csv


class _StubInterface:
    def set_player(self, player):
        self.player = player


def _mixed_context(seed=7):
    """GameContext whose board is the mixed-cost test map (classic tickets
    are irrelevant here — these tests never draw tickets)."""
    context = GameContext(["p0", "p1"], seed=seed)
    context.map_graph = MapGraph(player_count=2, map_name=str(write_map_csv(MIXED_ROWS)))
    return context


def _make_player(context):
    player = Player("p0", _StubInterface(), "p0", "red")
    player.attach(context, [player])
    return player


class ClaimSpendTests(unittest.TestCase):
    def test_payment_none_reproduces_classic_spend(self):
        route = Route("A", "B", 4, "R", "A-B-1")
        spend = claim_spend(ClaimRoute("A-B-1", "R", 1), route)
        self.assertEqual(+spend, Counter({"R": 3, "L": 1}))
        spend = claim_spend(ClaimRoute("A-B-1", "L", 4), route)
        self.assertEqual(+spend, Counter({"L": 4}))

    def test_mixed_payment_spend(self):
        route = Route("A", "B", 5, "X", "A-B-1", cost=parse_cost("3U+2R", 5))
        action = ClaimRoute("A-B-1", "U", 1, payment=(("U", 1), ("R", 0)))
        self.assertEqual(+claim_spend(action, route), Counter({"U": 2, "R": 2, "L": 1}))

    def test_locomotive_floor_payment_spend(self):
        route = Route("A", "B", 5, "X", "A-B-1", cost=parse_cost("2L+3U", 5))
        action = ClaimRoute("A-B-1", "U", 3, payment=(("L", 2), ("U", 1)))
        self.assertEqual(+claim_spend(action, route), Counter({"L": 3, "U": 2}))


class PaymentExecutionTests(unittest.TestCase):
    def test_apply_claim_spends_the_payment(self):
        context = _mixed_context()
        player = _make_player(context)
        hand = player.get_hand()
        hand.clear()
        hand.update({"U": 3, "R": 2, "L": 1})
        route = next(r for r in context.get_map().routes
                     if (r.city1, r.city2) == ("Ax", "Bx"))
        action = ClaimRoute(route.route_id, "U", 0, payment=(("U", 0), ("R", 0)))
        player._Player__apply_claim(action)
        self.assertEqual(route.claimed_by, "p0")
        self.assertEqual(+player.get_hand(), Counter({"L": 1}))
        self.assertEqual(player.trains_remaining, 45 - 5)

    def test_apply_claim_classic_path_unchanged(self):
        context = GameContext(["p0", "p1"], seed=11)
        player = _make_player(context)
        route = context.get_map().get_available_routes("p0")[0]
        hand = player.get_hand()
        hand.clear()
        hand.update({route.color if route.color != "X" else "R": route.length})
        color = route.color if route.color != "X" else "R"
        player._Player__apply_claim(ClaimRoute(route.route_id, color, 0))
        self.assertEqual(route.claimed_by, "p0")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest discover -s quality/tests -p "test_claim_payment.py" -v`
Expected: FAIL — `ClaimRoute.__init__() got an unexpected keyword argument 'payment'` / `cannot import name 'claim_spend'`.

- [ ] **Step 3: Implement**

In `actions.py`, replace the `ClaimRoute` dataclass:

```python
@dataclass(frozen=True)
class ClaimRoute(Action):
    """Claim `route_id`. For classic single-component routes, `payment` is
    None and the spend is `locomotives` L cards plus `color` cards for the
    rest (`color` is "L" when locomotives cover the whole route). For mixed
    costs, `payment` holds one (chosen_color, locomotives_substituted) pair
    per cost component in cost order — locomotive components as ("L", count)
    — and `color`/`locomotives` are summaries (first color actually spent,
    total locomotives) kept for bots' ranking keys and logs."""
    route_id: str
    color: str
    locomotives: int
    payment: 'Optional[Tuple[Tuple[str, int], ...]]' = None
```

Add below `legal_claim_actions`:

```python
def claim_spend(action: ClaimRoute, route: Route) -> 'Counter[str]':
    """Exactly which cards `action` burns — the bot-side valuation hook.

    Insertion order (L first, then colors in component order) matches the
    card list Player.__apply_claim discards, so replay-sensitive consumers
    see the same sequence either way.
    """
    spend: 'Counter[str]' = Counter()
    if action.payment is None:
        spend["L"] = action.locomotives
        if action.color != "L":
            spend[action.color] += route.length - action.locomotives
        return spend
    spend["L"] = 0
    for (color, locos), component in zip(action.payment, route.cost):
        spend["L"] += locos
        remainder = component.count - locos
        if remainder:
            spend[color] += remainder
    return spend
```

In `player.py`, replace `__apply_claim`:

```python
    def __apply_claim(self, action: ClaimRoute) -> None:
        route = self._game.get_map().route_by_id(action.route_id)
        self._spend_cards(list(claim_spend(action, route).elements()))
        self.__claim_route(route)
        self.update_longest_path(route)
```

and add `claim_spend` to the existing `from ticket_to_ride.engine.actions import (...)` line.

Note: `Counter.elements()` yields in insertion order — L entries first, then the color(s) — which is exactly the `["L"] * locomotives + [color] * needed` list the old code built, so the discard-pile order (and therefore deck reshuffles) is unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest discover -s quality/tests -p "test_claim_payment.py" -v`
Expected: all PASS.

- [ ] **Step 5: Run the whole suite**

Run: `uv run python -m unittest discover -s quality/tests 2>&1 | tail -3`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/engine/actions.py services/native-runtime/src/ticket_to_ride/engine/player.py quality/tests/test_claim_payment.py
git commit -m "feat(engine): ClaimRoute.payment with claim_spend execution hook"
```

---

### Task 5: Payment enumeration in the hot core

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/engine/actions.py` (`enumerate_claim_actions` ~line 124, `affordable_route_options` ~line 150)
- Test: `quality/tests/test_claim_payment.py` (extend)

**Interfaces:**
- Consumes: `CostComponent` predicates (Task 2), `Route.cost` (Task 3), `ClaimRoute.payment` (Task 4).
- Produces:
  - `_is_classic_cost(cost) -> bool` — exactly one component with one non-L option (fixed color or grey): the verbatim-old fast path.
  - `_payment_claim_actions(route, hand) -> List[ClaimRoute]` — every legal payment of a non-classic cost, deduplicated by card multiset, deterministic order.
  - `enumerate_claim_actions` / `affordable_route_options` route through the fast path or the payment enumerator; single-component behavior byte-identical.

- [ ] **Step 1: Write the failing tests**

Append to `quality/tests/test_claim_payment.py`:

```python
from ticket_to_ride.engine.actions import legal_claim_actions


def _hand(player, **cards):
    hand = player.get_hand()
    hand.clear()
    hand.update(cards)
    return hand


def _actions_for(context, player, city_pair):
    route = next(r for r in context.get_map().routes
                 if (r.city1, r.city2) == city_pair)
    return route, [a for a in legal_claim_actions(player)
                   if a.route_id == route.route_id]


class PaymentEnumerationTests(unittest.TestCase):
    def setUp(self):
        self.context = _mixed_context()
        self.player = _make_player(self.context)

    def test_fixed_mixed_cost_needs_both_colors(self):
        # Ax-Bx costs 3U+2R
        _hand(self.player, U=3, R=1)
        _, actions = self._route_actions(("Ax", "Bx"))
        self.assertEqual(actions, [])
        _hand(self.player, U=3, R=2)
        route, actions = self._route_actions(("Ax", "Bx"))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].payment, (("U", 0), ("R", 0)))
        self.assertEqual(actions[0].locomotives, 0)

    def test_locomotives_substitute_into_any_component(self):
        _hand(self.player, U=2, R=2, L=1)  # short one U for 3U+2R
        route, actions = self._route_actions(("Ax", "Bx"))
        spends = {tuple(sorted(claim_spend(a, route).items())) for a in actions}
        self.assertIn((("L", 1), ("R", 2), ("U", 2)), spends)

    def test_option_set_is_uniform_per_segment(self):
        # Bx-Cx costs 2(G|B)+2X
        _hand(self.player, G=1, B=1, W=2)  # can't pay (G|B) with 1G+1B
        _, actions = self._route_actions(("Bx", "Cx"))
        self.assertEqual(actions, [])
        _hand(self.player, G=2, W=2)
        _, actions = self._route_actions(("Bx", "Cx"))
        self.assertTrue(actions)

    def test_grey_component_takes_any_uniform_color(self):
        _hand(self.player, B=2, Y=2)
        route, actions = self._route_actions(("Bx", "Cx"))  # 2(G|B)+2X
        spends = {tuple(sorted((+claim_spend(a, route)).items())) for a in actions}
        self.assertIn((("B", 2), ("Y", 2)), spends)

    def test_actions_deduped_by_card_multiset(self):
        # 2(G|B)+2X with an all-green hand: "G for the set, G for the grey"
        # is one multiset however the components are assigned
        _hand(self.player, G=4)
        route, actions = self._route_actions(("Bx", "Cx"))
        spends = [tuple(sorted((+claim_spend(a, route)).items())) for a in actions]
        self.assertEqual(len(spends), len(set(spends)))

    def test_pure_locomotive_route(self):
        # Cx-Dx costs 3L
        _hand(self.player, L=2, U=8)
        _, actions = self._route_actions(("Cx", "Dx"))
        self.assertEqual(actions, [])
        _hand(self.player, L=3)
        _, actions = self._route_actions(("Cx", "Dx"))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].payment, (("L", 3),))
        self.assertEqual(actions[0].color, "L")

    def test_locomotive_floor_with_extras(self):
        # Ax-Dx costs 2L+3U: any locos >= 2 with Blues for the rest
        _hand(self.player, L=4, U=1)
        route, actions = self._route_actions(("Ax", "Dx"))
        spends = {tuple(sorted((+claim_spend(a, route)).items())) for a in actions}
        self.assertIn((("L", 4), ("U", 1)), spends)
        self.assertNotIn((("L", 2), ("U", 3)), spends)  # only 1 U in hand

    def test_affordability_reports_min_locos(self):
        from ticket_to_ride.engine.actions import affordable_route_options
        map_graph = self.context.get_map()
        _hand(self.player, L=3, U=3)
        options = affordable_route_options(
            map_graph.routes, map_graph.sibling_index,
            lambda route: route.claimed_by, "p0", 2,
            self.player.get_hand(), self.player.trains_remaining)
        by_pair = {(r.city1, r.city2): n for r, n in options}
        self.assertEqual(by_pair[("Ax", "Dx")], 2)   # 2L+3U: floor is 2
        self.assertEqual(by_pair[("Cx", "Dx")], 3)   # 3L

    def _route_actions(self, pair):
        return _actions_for(self.context, self.player, pair)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest discover -s quality/tests -p "test_claim_payment.py" -v`
Expected: new tests FAIL (mixed routes yield no actions or crash on `route.color is None`); Task 4 tests still pass.

- [ ] **Step 3: Implement**

In `actions.py`, add `from itertools import combinations, product` (extend the existing import) and add:

```python
def _is_classic_cost(cost) -> bool:
    """One component, one non-locomotive option: today's single-color/grey
    route. This is the hot path and must keep its exact historical
    enumeration order."""
    return (len(cost) == 1 and len(cost[0].options) == 1
            and not cost[0].is_locomotive())


def _payment_claim_actions(route: Route, hand: 'Counter[str]') -> List[ClaimRoute]:
    """Every legal payment of a non-classic cost: one canonical ClaimRoute
    per distinct card multiset spent, in deterministic enumeration order.

    Uniform color per component (grey ranges over the hand's colors, like
    the classic gray-route enumeration); locomotives substitute per
    component; "L" components contribute a locomotive floor.
    """
    locomotives = hand.get("L", 0)
    loco_floor = 0
    color_components = []
    for component in route.cost:
        if component.is_locomotive():
            loco_floor += component.count
        else:
            color_components.append(component)
    if loco_floor > locomotives:
        return []

    def choices(component):
        if component.is_grey():
            # A grey component may be paid wholly with locomotives even when
            # the hand contains no real-color cards.
            return list(CARD_COLORS)
        return list(component.options)

    actions: List[ClaimRoute] = []
    seen: 'set[tuple]' = set()
    for assignment in product(*(choices(c) for c in color_components)):
        for substitutions in product(*(range(c.count + 1) for c in color_components)):
            total_locos = loco_floor + sum(substitutions)
            if total_locos > locomotives:
                continue
            needed: 'Counter[str]' = Counter()
            for component, color, locos in zip(color_components, assignment, substitutions):
                needed[color] += component.count - locos
            if any(hand.get(color, 0) < count for color, count in needed.items()):
                continue
            spend_key = (tuple(sorted((c, n) for c, n in needed.items() if n)),
                         total_locos)
            if spend_key in seen:
                continue
            seen.add(spend_key)
            payment = []
            color_iter = iter(zip(assignment, substitutions))
            for component in route.cost:
                if component.is_locomotive():
                    payment.append(("L", component.count))
                else:
                    payment.append(next(color_iter))
            first_color = next(
                (color for (color, locos), component in zip(payment, route.cost)
                 if not component.is_locomotive() and component.count - locos > 0),
                "L",
            )
            actions.append(ClaimRoute(route.route_id, first_color, total_locos,
                                      payment=tuple(payment)))
    return actions
```

Rework the body of `enumerate_claim_actions` (the surrounding signature/docstring stay):

```python
    locomotives = hand.get("L", 0)
    actions: List[ClaimRoute] = []
    for route in claimable_routes(routes, siblings_by_key, claim_of,
                                  player_id, player_count, trains_remaining):
        if not _is_classic_cost(route.cost):
            actions.extend(_payment_claim_actions(route, hand))
            continue
        for spent_locos in range(min(locomotives, route.length) + 1):
            needed = route.length - spent_locos
            if needed == 0:
                actions.append(ClaimRoute(route.route_id, "L", spent_locos))
                continue
            colors = [route.color] if route.color != "X" else [c for c in hand if c != "L"]
            for color in colors:
                if hand.get(color, 0) >= needed:
                    actions.append(ClaimRoute(route.route_id, color, spent_locos))
    return actions
```

Rework the body of `affordable_route_options` the same way:

```python
    if not hand.total():
        return []
    locomotives = hand.get("L", 0)
    colors = Counter({c: n for c, n in hand.items() if c != "L" and n > 0})
    most_common = max(colors.values(), default=0)
    options: 'List[Tuple[Route, int]]' = []
    for route in claimable_routes(routes, siblings_by_key, claim_of,
                                  player_id, player_count, trains_remaining):
        if not _is_classic_cost(route.cost):
            payments = _payment_claim_actions(route, hand)
            if payments:
                options.append((route, min(a.locomotives for a in payments)))
            continue
        for n in range(locomotives + 1):
            needed = route.length - n
            if colors.get(route.color, 0) >= needed or (route.color == "X" and most_common >= needed):
                options.append((route, n))
                break
    return options
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest discover -s quality/tests -p "test_claim_payment.py" -v`
Expected: all PASS.

- [ ] **Step 5: Run the parity oracles and full suite**

Run: `uv run python -m unittest discover -s quality/tests 2>&1 | tail -3`
Expected: OK — in particular `test_engine_caching.AffordabilityParityTests` (embedded old-behavior oracles) must pass untouched.

- [ ] **Step 6: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/engine/actions.py quality/tests/test_claim_payment.py
git commit -m "feat(engine): payment enumeration for mixed costs, classic fast path preserved"
```

---

### Task 6: Supported bot planning shims and explicit ML features

**Files:**
- Modify: `integrations/external/bots/example_bot.py`
- Modify: `integrations/external/bots/qualifier_bot.py` (~lines 112, 315-318, 332, 423)
- Modify: `integrations/external/ml/xgb_features.py`
- Test: `quality/tests/test_mixed_map_bots.py`

**Interfaces:**
- Consumes: `Route.payment_colors()` (Task 3); mixed test map via `write_map_csv`/`MIXED_ROWS` (Task 3 tests).
- Produces: bots that never read `route.color` on a route that might be mixed; behavior on classic maps provably unchanged (the shims reduce to the old expressions when `payment_colors()` has 1 or all-8 members).

- [ ] **Step 1: Write the failing test**

Create `quality/tests/test_mixed_map_bots.py`:

```python
"""Planner bots must stay legal (and not crash) on mixed-cost maps."""
import random
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "applications", REPO / "integrations"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from external.bots.example_bot import ExampleBot
from external.bots.qualifier_bot import QualifierBot
from external.bots.random_bot import RandomBot
from notebook_harness.game_runner import initialize_game

from quality.tests.test_route_costs import MIXED_ROWS, write_map_csv

# a denser mixed map so full games are playable: the mixed shapes plus
# enough classic filler for tickets-free play to proceed
PLAYABLE_ROWS = MIXED_ROWS + [
    ("Ax", "Ex", "2", "G", ""),
    ("Bx", "Ex", "3", "X", ""),
    ("Cx", "Ex", "1", "Y", ""),
    ("Dx", "Ex", "4", "O", ""),
    ("Ax", "Fx", "3", "P", ""),
    ("Fx", "Dx", "2", "W", ""),
    ("Fx", "Ex", "2", "X", ""),
]


class MixedMapBotSmokeTests(unittest.TestCase):
    def test_planner_bots_finish_a_mixed_map_game(self):
        random.seed(90210)
        map_path = write_map_csv(PLAYABLE_ROWS)
        harness = initialize_game(
            [ExampleBot(), QualifierBot(), RandomBot()],
            map_name=str(map_path), seed=90210)
        harness.play()  # must not raise
        self.assertGreater(harness.snapshot_count(), 0)


if __name__ == "__main__":
    unittest.main()
```

Note: the classic ticket deck is used as fallback for this map (its cities never connect, so tickets simply score negative) — the point is legality/crash-freedom, not strength.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest discover -s quality/tests -p "test_mixed_map_bots.py" -v`
Expected: FAIL — TypeError/KeyError from `route.color is None` sites (e.g. `hand.get(None, 0)` comparisons succeed silently but `min()` over empty `colors` raises ValueError, or `reserved[None]` pollution), or an assertion crash inside planning.

- [ ] **Step 3: Apply the shims to BOTH bot files**

Apply the equivalent `payment_colors()` planning reductions in `example_bot.py`
and `qualifier_bot.py`. RandomBot already selects directly from the legal menu
and only needs smoke coverage. Fable and Codex Best are deferred.

**(a) Color-candidate lists** — apply at the corresponding Example and Qualifier sites:

```python
# before
colors = [route.color] if route.color != "X" else self._CARD_COLORS
# after
colors = [c for c in self._CARD_COLORS if c in route.payment_colors()]
```

Immediately after each site, guard the empty case (pure-locomotive routes have no payment colors). In `best_turns` loops, after computing `colors`, add:

```python
        if not colors:
            return float("inf")  # locomotive-only: not plannable from colors
```

(match the function's existing "cannot assemble" return value — both functions return infinity for unassemblable routes; keep the exact literal each function already uses).

In any locomotive-worth loop:

```python
            colors = [c for c in self._CARD_COLORS if c in route.payment_colors()]
            if not colors:
                continue
```

**(b) Reserved-stack accumulation** — both supported planners:

```python
# before
if route.color == "X":
    grey_needed += route.length
else:
    reserved[route.color] += route.length
# after
options = route.payment_colors()
if len(options) == 1:
    reserved[next(iter(options))] += route.length
else:
    grey_needed += route.length
```

(Classic: fixed color has exactly 1 option → same bucket; grey has 8 → grey bucket. Mixed and pure-loco routes land in the flexible grey bucket, which is the sane planning default until the strategy round.)

**(c) Locomotive-target pick** — both supported planners:

```python
# before
target = stack_color if longest.color == "X" else longest.color
# after
longest_options = longest.payment_colors()
target = (next(iter(longest_options)) if len(longest_options) == 1
          else stack_color)
```

**(d) Forced-claim gray bucket** — both supported planners:

```python
# before
gray = [pick for pick in options if pick[0].color == "X"]
# after
gray = [pick for pick in options if len(pick[0].payment_colors()) != 1]
```

(Classic grey → 8 ≠ 1 → gray bucket, fixed → 1 → colored bucket, unchanged. Mixed/pure-loco → flexible bucket.)

The ranking keys on actions (`needs.get(a.color, 0), -hand.get(a.color, 0)`) need **no** change: mixed actions carry a real first-spent color (or `"L"`) in `a.color` by Task 5's construction.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest discover -s quality/tests -p "test_mixed_map_bots.py" -v`
Expected: PASS.

- [ ] **Step 5: Add explicit mixed-cost ML features**

Keep classic route-color features unchanged. For mixed routes add component
count, option-set count, grey-space count, required-locomotive-space count,
distinct mentioned real colors, total declared real-color options, and
per-real-color eligible-space counts. Add focused feature tests; do not map a
mixed route to grey.

- [ ] **Step 6: Full suite (classic-map parity gate for the bots)**

Run: `uv run python -m unittest discover -s quality/tests 2>&1 | tail -3`
Expected: OK.

- [ ] **Step 7: Commit**

```bash
git add integrations/external/bots/example_bot.py integrations/external/bots/qualifier_bot.py integrations/external/ml/xgb_features.py quality/tests/test_mixed_map_bots.py quality/tests/test_xgb_features.py
git commit -m "feat(bots): payment_colors shims so planners stay legal on mixed maps"
```


---

### Task 7: Per-segment render specs and the gradient config (Python side)

**Files:**
- Modify: `services/native-runtime/src/ticket_to_ride/board_view.py`
- Test: `quality/tests/test_board_segments.py`

**Interfaces:**
- Consumes: `Route.cost` (Task 3).
- Produces:
  - `LOCOMOTIVE_GRADIENT_STOPS: List[str]` = `["red", "orange", "yellow", "green", "blue", "indigo", "violet"]` in `board_view.py`.
  - `card_color_hex()["L"]` becomes `{"stops": LOCOMOTIVE_GRADIENT_STOPS}` (dict, not string).
  - `build_segments(route: Route) -> List[Dict[str, Any]]` — one `{"kind", "colors"}` dict per train space, component order; kinds: `"solid"` (1 hex), `"options"` (n hexes), `"loco"` (gradient stops).
  - `build_edges` / `build_culled_edges` edge dicts gain `data["segments"] = build_segments(route)`.

- [ ] **Step 1: Write the failing tests**

Create `quality/tests/test_board_segments.py`:

```python
"""Per-segment render specs: the display contract for mixed costs."""
import unittest

from ticket_to_ride.board_view import (
    LOCOMOTIVE_GRADIENT_STOPS, build_edges, build_segments, card_color_hex,
)
from ticket_to_ride.engine.state.costs import parse_cost
from ticket_to_ride.engine.state.map import MapGraph, Route

from quality.tests.test_route_costs import MIXED_ROWS, write_map_csv


class BuildSegmentsTests(unittest.TestCase):
    def test_classic_route_is_uniform_solid(self):
        route = Route("A", "B", 4, "R", "A-B-1")
        segments = build_segments(route)
        self.assertEqual(len(segments), 4)
        self.assertEqual(segments[0], {"kind": "solid", "colors": ["#d62728"]})
        self.assertEqual(len({str(s) for s in segments}), 1)

    def test_grey_component_renders_solid_grey(self):
        route = Route("A", "B", 3, "X", "A-B-1")
        self.assertEqual(build_segments(route)[0],
                         {"kind": "solid", "colors": ["#999999"]})

    def test_mixed_cost_orders_segments_by_component(self):
        route = Route("A", "B", 5, "X", "A-B-1", cost=parse_cost("3U+2R", 5))
        segments = build_segments(route)
        self.assertEqual([s["colors"][0] for s in segments],
                         ["#1f77b4"] * 3 + ["#d62728"] * 2)

    def test_option_set_lists_both_colors(self):
        route = Route("A", "B", 2, "X", "A-B-1", cost=parse_cost("2(G|B)", 2))
        self.assertEqual(build_segments(route)[0],
                         {"kind": "options", "colors": ["#2ca02c", "#1f1f1f"]})

    def test_locomotive_component_carries_gradient_stops(self):
        route = Route("A", "B", 3, "X", "A-B-1", cost=parse_cost("3L", 3))
        self.assertEqual(build_segments(route)[0],
                         {"kind": "loco", "colors": LOCOMOTIVE_GRADIENT_STOPS})


class EdgePayloadTests(unittest.TestCase):
    def test_every_edge_carries_segments_of_route_length(self):
        graph = MapGraph(player_count=2, map_name=str(write_map_csv(MIXED_ROWS)))
        edges = build_edges(graph, {}, {})
        for edge in edges:
            self.assertEqual(len(edge["data"]["segments"]), edge["data"]["length"])

    def test_locomotive_card_color_is_gradient_stops(self):
        self.assertEqual(card_color_hex()["L"],
                         {"stops": LOCOMOTIVE_GRADIENT_STOPS})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest discover -s quality/tests -p "test_board_segments.py" -v`
Expected: FAIL — `cannot import name 'LOCOMOTIVE_GRADIENT_STOPS'`.

- [ ] **Step 3: Implement in `board_view.py`**

Replace the `_LOCOMOTIVE_HEX` constant block with:

```python
# Locomotives read as "any color": a rainbow gradient, stored as stops so
# each renderer can materialize it (CSS linear-gradient for card faces, an
# SVG <linearGradient> for the market pie, ctx.createLinearGradient for the
# board canvas). One definition; every widget that shows an L updates
# together.
LOCOMOTIVE_GRADIENT_STOPS: List[str] = [
    "red", "orange", "yellow", "green", "blue", "indigo", "violet",
]
```

Update `card_color_hex` (keep its docstring, adjust the locomotive line):

```python
    colors = {letter: hex_ for letter, hex_ in _ROUTE_COLOR_HEX.items() if letter != "X"}
    colors["L"] = {"stops": LOCOMOTIVE_GRADIENT_STOPS}
    return colors
```

Add after `_edge_color`:

```python
def build_segments(route: Route) -> List[Dict[str, Any]]:
    """One render spec per train space, in cost-component order.

    kinds: "solid" (one hex — fixed color, and grey which by validation
    never appears inside an option set), "options" (n hexes, drawn as n
    diagonal bands, two of which are the classic split triangles), "loco"
    (rainbow gradient stops).
    """
    segments: List[Dict[str, Any]] = []
    for component in route.cost:
        if component.is_locomotive():
            entry = {"kind": "loco", "colors": LOCOMOTIVE_GRADIENT_STOPS}
        elif len(component.options) == 1:
            entry = {"kind": "solid",
                     "colors": [_ROUTE_COLOR_HEX.get(component.options[0], "#999999")]}
        else:
            entry = {"kind": "options",
                     "colors": [_ROUTE_COLOR_HEX.get(c, "#999999")
                                for c in component.options]}
        segments.extend([entry] * component.count)
    return segments
```

In **both** `build_edges` and `build_culled_edges`, extend the `"data"` dict:

```python
                "data": {
                    "length": route.length,
                    "color": route.color,
                    "claimedBy": owner,          # (None in build_culled_edges)
                    "segments": build_segments(route),
                },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest discover -s quality/tests -p "test_board_segments.py" -v`
Expected: all PASS.

- [ ] **Step 5: Full suite (display schema consumers)**

Run: `uv run python -m unittest discover -s quality/tests 2>&1 | tail -3`
Expected: OK (`test_match_api`, `test_notebook_harness_rendering` exercise the edge schema).

- [ ] **Step 6: Commit**

```bash
git add services/native-runtime/src/ticket_to_ride/board_view.py quality/tests/test_board_segments.py
git commit -m "feat(display): per-segment render specs and locomotive gradient stops"
```

---

### Task 8: Widget renderers (canvas painter, card faces, pie)

**Files:**
- Modify: `applications/notebook_harness/widget-src/src/route_graph_widget.js` (`paint_train_spaces`, ~lines 174-264)
- Modify: `applications/notebook_harness/widget-src/src/info_bar_widget.js`
- Modify (regenerated by build): `applications/notebook_harness/static/route_graph_widget.js`, `applications/notebook_harness/static/info_bar_widget.js`
- Create: `$SCRATCH/probe_segments.py` (verification, not committed)

**Interfaces:**
- Consumes: `data.segments` entries `{kind: "solid"|"options"|"loco", colors: [...]}` and `colors["L"] = {stops: [...]}` (Task 7).
- Produces: per-rectangle painting — solid as today; `options` = n diagonal bands (n=2 is the corner-to-corner triangle split); `loco` = canvas linear gradient; card faces/pie tolerate both string colors and `{stops}` dicts.

- [ ] **Step 1: Update the canvas painter**

In `route_graph_widget.js`, inside `paint_train_spaces`, replace the per-space fill block (currently `ctx.fillStyle = baseColor; ctx.fillRect(...)`) with segment-aware painting. Insert before the loop:

```js
        const segments = (link.data && Array.isArray(link.data.segments))
            ? link.data.segments : null;
```

Then inside the loop, replace:

```js
            ctx.fillStyle = baseColor;
            ctx.fillRect(-carLength / 2, -train_space_width / 2, carLength, train_space_width);
```

with:

```js
            const seg = (segments && segments[i])
                ? segments[i]
                : { kind: "solid", colors: [baseColor] };
            const x0 = -carLength / 2;
            const y0 = -train_space_width / 2;
            if (seg.kind === "loco") {
                // rainbow gradient along the car, from the shared stops
                const grad = ctx.createLinearGradient(x0, 0, x0 + carLength, 0);
                const stops = seg.colors && seg.colors.length ? seg.colors : ["#999"];
                stops.forEach((c, k) => grad.addColorStop(
                    stops.length === 1 ? 0 : k / (stops.length - 1), c));
                ctx.fillStyle = grad;
                ctx.fillRect(x0, y0, carLength, train_space_width);
            } else if (seg.colors && seg.colors.length > 1) {
                // n diagonal bands between cuts parallel to the anti-diagonal;
                // n = 2 is exactly the corner-to-corner split into two triangles.
                const n = seg.colors.length;
                ctx.save();
                ctx.beginPath();
                ctx.rect(x0, y0, carLength, train_space_width);
                ctx.clip();
                for (let k = 0; k < n; k++) {
                    // cut lines x/w + y/h = 2f sweep corner to corner as f: 0 -> 1
                    const f0 = k / n;
                    const f1 = (k + 1) / n;
                    ctx.fillStyle = seg.colors[k];
                    ctx.beginPath();
                    ctx.moveTo(x0 + 2 * f0 * carLength, y0);
                    ctx.lineTo(x0, y0 + 2 * f0 * train_space_width);
                    ctx.lineTo(x0, y0 + 2 * f1 * train_space_width);
                    ctx.lineTo(x0 + 2 * f1 * carLength, y0);
                    ctx.closePath();
                    ctx.fill();
                }
                ctx.restore();
            } else {
                ctx.fillStyle = (seg.colors && seg.colors[0]) || baseColor;
                ctx.fillRect(x0, y0, carLength, train_space_width);
            }
```

The existing `strokeRect` outline and the claimed-inset block after it stay exactly as they are (they draw over whatever base was painted). For the outline's contrast check, keep `is_dark_color(baseColor)` — the roadbed/base color remains the contrast reference.

- [ ] **Step 2: Update the info bar (card faces + pie)**

In `info_bar_widget.js`, add near the top:

```js
const SVG_NS = "http://www.w3.org/2000/svg";
let gradient_serial = 0;

// colors[letter] is either a CSS color string or {stops: [...]} (the
// locomotive rainbow). Older stored payloads may still carry a flat string.
function css_color(value) {
    if (!value) return "#999";
    if (typeof value === "string") return value;
    if (Array.isArray(value.stops)) {
        return `linear-gradient(to right, ${value.stops.join(", ")})`;
    }
    return "#999";
}

// SVG fills can't take CSS gradients: materialize {stops} as a
// <linearGradient> def on this pie's own svg and return its url() ref.
function svg_fill(svg, value) {
    if (!value) return "#999";
    if (typeof value === "string") return value;
    if (Array.isArray(value.stops)) {
        const id = `pie-grad-${++gradient_serial}`;
        const grad = document.createElementNS(SVG_NS, "linearGradient");
        grad.setAttribute("id", id);
        value.stops.forEach((c, i) => {
            const stop = document.createElementNS(SVG_NS, "stop");
            stop.setAttribute("offset",
                `${value.stops.length === 1 ? 0 : (100 * i) / (value.stops.length - 1)}%`);
            stop.setAttribute("stop-color", c);
            grad.appendChild(stop);
        });
        svg.appendChild(grad);
        return `url(#${id})`;
    }
    return "#999";
}
```

Then swap the three fill sites:
- `build_pie` single-slice circle: `circle.setAttribute("fill", svg_fill(svg, colors[segments[0].color]));`
- `build_pie` slice loop: `path.setAttribute("fill", svg_fill(svg, colors[seg.color]));`
- face-up card faces: `card.style.background = css_color(colors[letter]);`

(The existing `.market-card-locomotive` CSS sheen is overridden by the inline gradient shorthand — the rainbow *is* the wild look now; leave the CSS class in place for stored-payload fallback rendering.)

- [ ] **Step 3: Check the player list widget for card-color fills**

Run: `grep -n "colors\[" applications/notebook_harness/widget-src/src/player_list_widget.js`
If it paints card colors from the shared map, apply the same `css_color()` helper there (copy the function; these bundles don't share modules). If no hits, move on.

- [ ] **Step 4: Rebuild the bundles**

Run: `cd applications/notebook_harness/widget-src && npm run build`
Expected: esbuild writes `../static/route_graph_widget.js`, `../static/info_bar_widget.js`, `../static/player_list_widget.js` without errors.

- [ ] **Step 5: Live probe of the widget payload contract**

Create `$SCRATCH/probe_segments.py`:

```python
"""Probe: every board_at edge carries well-formed data.segments."""
import random
import sys
from pathlib import Path

REPO = Path("/Users/lucasstarkey/Documents/GitHub/ticket_to_ride")
sys.path.insert(0, str(REPO / "applications"))
sys.path.insert(0, str(REPO / "integrations"))

from external.bots.random_bot import RandomBot
from notebook_harness.game_runner import initialize_game

random.seed(777)
harness = initialize_game([RandomBot(), RandomBot()], seed=777)
harness.play()
nodes, edges = harness.board_at(harness.snapshot_count() - 1)
kinds = set()
for edge in edges:
    segments = edge["data"]["segments"]
    assert len(segments) == edge["data"]["length"], edge["id"]
    for seg in segments:
        assert seg["kind"] in {"solid", "options", "loco"}, seg
        assert seg["colors"], seg
        kinds.add(seg["kind"])
market = harness.market_at(0)
assert isinstance(market["colors"]["L"], dict) and market["colors"]["L"]["stops"]
print(f"{len(edges)} edges validated; kinds seen: {sorted(kinds)}; L gradient OK")
```

Run: `uv run python "$SCRATCH/probe_segments.py"`
Expected: `... edges validated; kinds seen: ['solid']; L gradient OK` (classic map: all solid).

- [ ] **Step 6: Full suite**

Run: `uv run python -m unittest discover -s quality/tests 2>&1 | tail -3`
Expected: OK.

- [ ] **Step 7: Commit**

```bash
git add applications/notebook_harness/widget-src/src/route_graph_widget.js applications/notebook_harness/widget-src/src/info_bar_widget.js applications/notebook_harness/static/
git commit -m "feat(widgets): segment-aware train spaces, rainbow locomotive gradient"
```

(Include `widget-src/src/player_list_widget.js` in the add if Step 3 touched it.)

---

### Task 9: End-to-end verification (parity, perf, suite)

**Files:**
- Create: `$SCRATCH/parity_mixed_after.json` (scratchpad artifact)
- Modify: `/Users/lucasstarkey/.claude/projects/-Users-lucasstarkey-Documents-GitHub-ticket-to-ride/memory/research-pipeline.md` (one-line addendum)

**Interfaces:**
- Consumes: Task 1's `$SCRATCH/parity_mixed_before.json` and baseline wall time.

- [ ] **Step 1: Byte-for-byte parity on existing maps**

Run:
```bash
cd /Users/lucasstarkey/Documents/GitHub/ticket_to_ride
uv run python operations/research/profile_engine.py --parity-dump "$SCRATCH/parity_mixed_after.json"
cmp "$SCRATCH/parity_mixed_before.json" "$SCRATCH/parity_mixed_after.json" && echo PARITY_OK
```
Expected: `PARITY_OK`. If it differs, bisect: the only legitimate sources of divergence are the fast-path conditions in Task 5 and the discard order in Task 4 — fix, do not regenerate the baseline.

- [ ] **Step 2: Perf check**

Run: `uv run python operations/research/profile_engine.py 2>&1 | tail -5`
Expected: within ~5% of Task 1's baseline (~0.38 s/game). The fast path is the old loop plus one `_is_classic_cost` tuple-length check per route, so any bigger regression means the fast path isn't being taken — investigate before accepting.

- [ ] **Step 3: Full suite, one last time**

Run: `uv run python -m unittest discover -s quality/tests 2>&1 | tail -3`
Expected: OK, ~280 tests.

- [ ] **Step 4: Update project memory**

Append one sentence to the engine-tooling paragraph of `research-pipeline.md` (the memory file above): routes now carry `Route.cost` component tuples (spec `docs/superpowers/specs/2026-07-15-mixed-route-costs-design.md`); classic maps byte-identical via the fast path; scoring rebalance + ferry/tunnel mechanics + generator support still pending.

- [ ] **Step 5: Final commit (docs)**

```bash
git add docs/superpowers/specs/2026-07-15-mixed-route-costs-design.md docs/superpowers/plans/2026-07-15-mixed-route-costs.md
git commit -m "docs: mixed route costs spec and implementation plan"
```
