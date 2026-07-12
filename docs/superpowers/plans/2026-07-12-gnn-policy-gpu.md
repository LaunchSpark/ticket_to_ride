# GNN Policy/Value Model (Windows + NVIDIA GPU) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Train a graph-neural-network state encoder with policy (imitation of QualifierBot/FableBestBot) and value (win prediction) heads on the DecisionRecord dataset, evaluated with a held-out-map protocol (train on classic, test on europe, and the reverse).

**v1 scope decision:** train and evaluate on `decision == "turn"` rows ONLY. `draw_second` and especially `keep_tickets` need real action features (kept count, total value, path distances, ticket overlap) that the v1 action schema does not carry — a type one-hot would train garbage rankings. A playable GnnBot is therefore **deferred to v2** alongside full decision coverage. Note also: training data reflects the *current engine rules* — Europe's ferry/tunnel/station mechanics are carried as data flags but not enforced in play. `map_profiles.jsonl` is the future surrogate-critic/novelty target archive; it is not part of this training loop.

**Architecture:** Engine stays ML-agnostic. `decision_export.py` rows + the map CSVs feed a framework-neutral numpy `TensorBuilder v1` (identity-free relational features: nodes = cities, edges = routes + virtual ticket edges, per-action encodings). A PyTorch Geometric message-passing encoder produces node/edge/global embeddings; a policy head scores each legal action (softmax over the variable-size menu), a value head predicts win probability from mean-pooled readout. Everything trains on GPU; weights save to `operations/research/results/`.

**Tech Stack:** Windows 11, NVIDIA GPU (CUDA 12.x driver), **Python 3.13 via uv** (torch has no 3.14 wheels), PyTorch cu124 wheels, torch_geometric (pure-Python core — no compiled pyg-lib extensions needed), numpy.

**Scope:** policy/value model only. The surrogate map-critic and generator loops are a follow-up plan — they consume this plan's encoder and the `map_profiles.jsonl` archive, but deliver independently.

---

## Context for the executor

- Repo: clone to the Windows machine; everything below runs from the repo root in PowerShell.
- The repo requires Python `>=3.12`; **pin 3.13** for torch compatibility: `uv python pin 3.13` (writes `.python-version`; do not commit it if the Mac side stays on 3.14 — add it to `.gitignore` in Task 1).
- Test suite: `uv run python -m unittest discover -s quality/tests` → must end `OK` (213 tests at time of writing) before every commit.
- Datasets: `uv run python operations/research/bot_lab.py …` writes `operations/research/results/records.jsonl`; `uv run python operations/research/decision_export.py` derives `decisions.jsonl`. Both are gitignored, regenerable, and deterministic given seeds.
- Commit after each task. End every commit message with:

```
Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```

## File map

| File | Change |
|---|---|
| `pyproject.toml` | Task 1: `ml` extra + torch CUDA index |
| `operations/research/bot_lab.py` | Task 2: `--map` flag so corpora span maps |
| `operations/research/tensorize.py` | Task 3 (new): TensorBuilder v1 (numpy, framework-neutral) |
| `quality/tests/test_tensorize.py` | Task 3 (new) |
| `operations/research/gnn/model.py` | Task 4 (new): PyG encoder + heads |
| `operations/research/gnn/train.py` | Task 5 (new): training + held-out-map eval CLI |
| `operations/research/gnn/__init__.py` | Task 4 (new, empty) |

---

## Task 1: GPU environment

- [ ] **Step 1: Pin Python and add the ml extra.**

```powershell
uv python pin 3.13
Add-Content .gitignore "`n.python-version"
```

In `pyproject.toml`, extend `[project.optional-dependencies]`:

```toml
ml = [
  "numpy>=2.0",
  "torch>=2.6",
  "torch-geometric>=2.6",
]
```

and add (top level, after `[project.scripts]`):

```toml
[tool.uv.sources]
torch = [{ index = "pytorch-cu124" }]

[[tool.uv.index]]
name = "pytorch-cu124"
url = "https://download.pytorch.org/whl/cu124"
explicit = true
```

- [ ] **Step 2: Sync and verify CUDA.**

```powershell
uv sync --extra notebooks --extra ml
uv run python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Expected: prints a `2.x+cu124` version, `True`, and your GPU's name. If `False`, update the NVIDIA driver before continuing — do not proceed on CPU.

- [ ] **Step 3: Full suite still green** — `uv run python -m unittest discover -s quality/tests` → `OK` (the engine must run identically under 3.13).

- [ ] **Step 4: Commit** — `git add pyproject.toml uv.lock .gitignore` / message `chore(ml): CUDA torch + PyG environment for the GNN work`.

## Task 2: Corpora that span maps

The held-out-map protocol needs decisions from both maps. `bot_lab.py` currently hardcodes the classic map.

- [ ] **Step 1: Add a `--map` flag.** In `operations/research/bot_lab.py`:
  - `run_matchup(tag, variant, opponent_name, games, seed_base, map_name="classic")` — pass through to `initialize_game(seats, map_name=map_name, seed=...)`.
  - argparse: `parser.add_argument("--map", default="classic")`; pass `args.map` at the `run_matchup` call site.
  - Add `"map": map_name` to ALL THREE row kinds: the games rows, the records rows (top-level meta, next to `"seed"` — `record.mapName` exists inside the payload but the meta key makes filtering cheap), and the `claim_events` rows (pass `map_name` through; route ids like `Paris-Zürich-1` are meaningless without map context).
  - The dashboard's `run_matchup` call passes no map and keeps working (default).

- [ ] **Step 2: Generate the training corpora** (~6 min total):

```powershell
uv run python operations/research/bot_lab.py --games 150 --opponents qualifier --tag corpus-classic --map classic --seed-base 9000 --fresh
uv run python operations/research/bot_lab.py --games 150 --opponents qualifier --tag corpus-europe --map europe --seed-base 50000
uv run python operations/research/decision_export.py
```

Expected: `exported ~40000 decisions from 300 games` (~130 decisions/game). `GameRecord.map_name` flows into each decision row via replay, so `state.map_name` distinguishes the corpora.

- [ ] **Step 3: Commit** — `feat(research): bot_lab --map flag for multi-map corpora`.

## Task 3: TensorBuilder v1 (numpy, framework-neutral)

**Files:** Create `operations/research/tensorize.py`, `quality/tests/test_tensorize.py`.

Design rules (identity-free for cross-map transfer): no city one-hots or per-city embeddings; mean-style normalizations by fixed game constants; virtual ticket edges carry the goals; the legal menu arrives from the engine so the model only ranks.

- [ ] **Step 1: Write the failing tests**

```python
# quality/tests/test_tensorize.py
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

_M = Path(__file__).resolve().parents[2] / "operations" / "research" / "tensorize.py"
_spec = importlib.util.spec_from_file_location("tensorize", _M)
tensorize = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tensorize)


def _fake_turn_row():
    return {
        "decision": "turn",
        "player": "p0",
        "state": {
            "map_name": "classic", "player_count": 2, "turn_number": 10,
            "score": 5, "trains_remaining": 40,
            "hand": {"R": 3, "L": 1},
            "tickets": [{"city1": "Denver", "city2": "El Paso", "value": 4,
                         "completed": False, "impossible": False}],
            "market": ["R", "G", "U", "W", "Y"],
            "discard": {"B": 2},
            "train_cards_in_deck": 80, "tickets_in_deck": 20,
            "claimed_by": {},
            "opponents": [{"player_id": "p1", "exposed": {}, "hand_count": 4,
                           "trains": 45, "score": 0, "ticket_count": 3}],
            "ticket_offer": None,
        },
        "legal_actions": [
            {"type": "DrawBlind"},
            {"type": "DrawFaceUp", "index": 0, "card": "R"},
            {"type": "ClaimRoute", "route_id": "Denver-Santa_Fe-1",
             "color": "R", "locomotives": 0},
            {"type": "DrawTickets"},
        ],
        "chosen": {"type": "ClaimRoute", "route_id": "Denver-Santa_Fe-1",
                   "color": "R", "locomotives": 0},
        "outcome": {"won": True, "margin": 12, "final_score": 90},
    }


class TensorizeTests(unittest.TestCase):
    def setUp(self):
        self.topo = tensorize.MapTopology.load("classic")
        self.sample = tensorize.build_sample(_fake_turn_row(), self.topo)

    def test_shapes_are_consistent(self):
        s = self.sample
        n_nodes = s["node_feats"].shape[0]
        self.assertEqual(n_nodes, 36)
        self.assertEqual(s["node_feats"].shape[1], tensorize.NODE_DIM)
        self.assertEqual(s["edge_index"].shape[0], 2)
        self.assertEqual(s["edge_index"].shape[1], s["edge_feats"].shape[0])
        self.assertEqual(s["edge_feats"].shape[1], tensorize.EDGE_DIM)
        self.assertEqual(s["globals"].shape[0], tensorize.GLOBAL_DIM)
        self.assertEqual(s["action_feats"].shape, (4, tensorize.ACTION_DIM))

    def test_virtual_ticket_edges_exist(self):
        # 100 routes * 2 directions + 1 pending ticket * 2 directions
        self.assertEqual(self.sample["edge_index"].shape[1], 202)
        self.assertEqual(self.sample["edge_feats"][:, tensorize.EF_IS_REAL].sum(), 200)
        virtual = self.sample["edge_feats"][self.sample["edge_feats"][:, tensorize.EF_IS_REAL] == 0]
        # the fake row's one ticket is pending: flag set, others clear
        self.assertTrue((virtual[:, tensorize.EF_TICKET_PENDING] == 1).all())
        self.assertTrue((virtual[:, tensorize.EF_TICKET_COMPLETED] == 0).all())
        self.assertTrue((virtual[:, tensorize.EF_TICKET_IMPOSSIBLE] == 0).all())

    def test_claim_action_points_at_its_route_edge(self):
        edge_ptr = int(self.sample["action_edge"][2])
        self.assertGreaterEqual(edge_ptr, 0)
        src, dst = self.sample["edge_index"][:, edge_ptr]
        cities = {self.topo.cities[src], self.topo.cities[dst]}
        self.assertEqual(cities, {"Denver", "Santa Fe"})
        # non-claim actions have no edge pointer
        self.assertEqual(int(self.sample["action_edge"][0]), -1)

    def test_label_is_the_chosen_index(self):
        self.assertEqual(int(self.sample["label"]), 2)
        self.assertEqual(float(self.sample["won"]), 1.0)

    def test_identity_free(self):
        # no feature dimension may scale with city count (36 vs 47)
        europe = tensorize.MapTopology.load("europe")
        row = _fake_turn_row()
        row["state"]["map_name"] = "europe"
        row["state"]["tickets"] = []
        row["legal_actions"] = [{"type": "DrawBlind"}]
        row["chosen"] = {"type": "DrawBlind"}
        sample = tensorize.build_sample(row, europe)
        self.assertEqual(sample["node_feats"].shape[1], tensorize.NODE_DIM)
        self.assertEqual(sample["edge_feats"].shape[1], tensorize.EDGE_DIM)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure** — `uv run python -m unittest quality.tests.test_tensorize` → ModuleNotFoundError/AttributeError.

- [ ] **Step 3: Implement `operations/research/tensorize.py`**

```python
"""TensorBuilder v1: symbolic DecisionRecords -> numpy graph tensors.

Framework-neutral (numpy only) and identity-free: no city one-hots, no
per-city embeddings — everything relational, so weights transfer across
maps. Consumes decision rows produced by decision_export.py plus the map
CSVs referenced by state.map_name.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
MAPS_DIR = REPO / "operations" / "data" / "maps"

CARD_COLORS = ["R", "B", "U", "G", "O", "P", "W", "Y", "L"]
ROUTE_COLORS = ["R", "B", "U", "G", "O", "P", "W", "Y", "X"]
ACTION_TYPES = ["ClaimRoute", "DrawFaceUp", "DrawBlind", "DrawTickets", "Pass", "KeepTickets"]

# node: [in_my_net, in_opp_net, degree/7, pending_ticket_endpoints/2,
#        completed_ticket_endpoints/2, unclaimed_length_at_node/20]
NODE_DIM = 6
# edge: [is_real, length_or_value/21, color_onehot(9), mine, theirs,
#        unclaimed, is_ferry, is_tunnel, is_double,
#        ticket_pending, ticket_completed, ticket_impossible]
EDGE_DIM = 20
EF_IS_REAL = 0
EF_TICKET_PENDING = 17
EF_TICKET_COMPLETED = 18
EF_TICKET_IMPOSSIBLE = 19
# globals: hand(9)/8, market(9)/3, discard_total/60, deck/72, my_trains/45,
#          opp_trains_min/45, opp_hand_max/25, opp_ticket_count/6, turn/120,
#          score_diff/60, pending_tickets/6, pending_value/40
GLOBAL_DIM = 9 + 9 + 10
# action: type_onehot(6) + card/spend color_onehot(9) + locomotives/4
ACTION_DIM = len(ACTION_TYPES) + 9 + 1


@dataclass
class _Route:
    route_id: str
    a: int
    b: int
    length: int
    color: str
    locomotives: int
    tunnel: bool
    double: bool


@dataclass
class MapTopology:
    name: str
    cities: 'list[str]'
    city_index: 'dict[str, int]'
    routes: 'list[_Route]'
    edge_of_route: 'dict[str, int]'   # route_id -> first directed edge row

    @classmethod
    def load(cls, map_name: str) -> "MapTopology":
        rows = list(csv.DictReader(open(MAPS_DIR / f"{map_name}.csv")))
        cities = sorted({r["city1"] for r in rows} | {r["city2"] for r in rows})
        index = {city: i for i, city in enumerate(cities)}
        group_counts: 'dict[tuple, int]' = {}
        keys = []
        for r in rows:
            key = (tuple(sorted((r["city1"], r["city2"]))), int(r["Distance"]))
            group_counts[key] = group_counts.get(key, 0) + 1
            keys.append(key)
        routes, seen = [], {}
        for r, key in zip(rows, keys):
            seen[key] = seen.get(key, 0) + 1
            route_id = f"{r['city1'].replace(' ', '_')}-{r['city2'].replace(' ', '_')}-{seen[key]}"
            routes.append(_Route(
                route_id, index[r["city1"]], index[r["city2"]],
                int(r["Distance"]), r["Color"],
                int(r.get("Locomotives") or 0),
                (r.get("Tunnel") or "").strip().lower() in {"1", "true", "yes"},
                group_counts[key] > 1,
            ))
        edge_of_route = {route.route_id: 2 * i for i, route in enumerate(routes)}
        return cls(map_name, cities, index, routes, edge_of_route)


def build_sample(row: dict, topo: MapTopology) -> dict:
    state = row["state"]
    n = len(topo.cities)
    claimed_by = state["claimed_by"]
    acting_player = row["player"]  # ownership compared directly, never inferred

    node = np.zeros((n, NODE_DIM), dtype=np.float32)
    edge_src, edge_dst, edge_feat = [], [], []

    for route in topo.routes:
        owner = claimed_by.get(route.route_id)
        mine = owner == acting_player
        theirs = owner is not None and owner != acting_player
        feats = np.zeros(EDGE_DIM, dtype=np.float32)
        feats[EF_IS_REAL] = 1.0
        feats[1] = route.length / 21.0
        feats[2 + ROUTE_COLORS.index(route.color)] = 1.0
        feats[11] = float(mine)
        feats[12] = float(theirs)
        feats[13] = float(owner is None)
        feats[14] = float(route.locomotives > 0)
        feats[15] = float(route.tunnel)
        feats[16] = float(route.double)
        for a, b in ((route.a, route.b), (route.b, route.a)):
            edge_src.append(a)
            edge_dst.append(b)
            edge_feat.append(feats)
        if mine:
            node[route.a, 0] = node[route.b, 0] = 1.0
        if theirs:
            node[route.a, 1] = node[route.b, 1] = 1.0
        if owner is None:
            node[route.a, 5] += route.length / 20.0
            node[route.b, 5] += route.length / 20.0
        node[route.a, 2] += 1 / 7.0
        node[route.b, 2] += 1 / 7.0

    for ticket in state["tickets"]:
        a, b = topo.city_index[ticket["city1"]], topo.city_index[ticket["city2"]]
        feats = np.zeros(EDGE_DIM, dtype=np.float32)
        feats[1] = ticket["value"] / 21.0
        pending = not ticket["completed"] and not ticket["impossible"]
        feats[EF_TICKET_PENDING] = float(pending)
        feats[EF_TICKET_COMPLETED] = float(ticket["completed"])
        feats[EF_TICKET_IMPOSSIBLE] = float(ticket["impossible"])
        # pending tickets light the node features the brainstorm asked for
        if pending:
            node[a, 3] += 0.5
            node[b, 3] += 0.5
        if ticket["completed"]:
            node[a, 4] += 0.5
            node[b, 4] += 0.5
        for s, d in ((a, b), (b, a)):
            edge_src.append(s)
            edge_dst.append(d)
            edge_feat.append(feats)

    hand = state["hand"]
    market = state["market"]
    opp = state["opponents"]
    pending = [t for t in state["tickets"] if not t["completed"] and not t["impossible"]]
    glob = np.array(
        [hand.get(c, 0) / 8.0 for c in CARD_COLORS]
        + [market.count(c) / 3.0 for c in CARD_COLORS]
        + [sum(state["discard"].values()) / 60.0,
           state["train_cards_in_deck"] / 72.0,
           state["trains_remaining"] / 45.0,
           min((o["trains"] for o in opp), default=45) / 45.0,
           max((o["hand_count"] for o in opp), default=0) / 25.0,
           max((o["ticket_count"] for o in opp), default=0) / 6.0,
           state["turn_number"] / 120.0,
           (state["score"] - max((o["score"] for o in opp), default=0)) / 60.0,
           len(pending) / 6.0,
           sum(t["value"] for t in pending) / 40.0],
        dtype=np.float32,
    )

    actions = row["legal_actions"]
    action_feats = np.zeros((len(actions), ACTION_DIM), dtype=np.float32)
    action_edge = np.full(len(actions), -1, dtype=np.int64)
    for i, action in enumerate(actions):
        action_feats[i, ACTION_TYPES.index(action["type"])] = 1.0
        color = action.get("card") or action.get("color")
        if color and color in CARD_COLORS:
            action_feats[i, len(ACTION_TYPES) + CARD_COLORS.index(color)] = 1.0
        action_feats[i, -1] = action.get("locomotives", 0) / 4.0
        if action["type"] == "ClaimRoute":
            action_edge[i] = topo.edge_of_route[action["route_id"]]

    return {
        "node_feats": node,
        "edge_index": np.array([edge_src, edge_dst], dtype=np.int64),
        "edge_feats": np.stack(edge_feat),
        "globals": glob,
        "action_feats": action_feats,
        "action_edge": action_edge,
        "label": np.int64(actions.index(row["chosen"])),
        "won": np.float32(row["outcome"]["won"]),
    }
```

- [ ] **Step 4: Run the tests** — module passes; full suite `OK`.
- [ ] **Step 5: Commit** — `feat(research): TensorBuilder v1 — identity-free graph tensors from DecisionRecords`.

## Task 4: The model (PyG encoder + policy/value heads)

**Files:** Create `operations/research/gnn/__init__.py` (empty), `operations/research/gnn/model.py`.

- [ ] **Step 1: Implement `model.py`**

```python
"""GNN state encoder with policy and value heads (PyTorch Geometric)."""
from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn
from torch_geometric.nn import MessagePassing
from torch_geometric.utils import softmax as segment_softmax


class EdgeConv(MessagePassing):
    """One round of message passing with edge features (mean aggregation
    — mean, not sum, for cross-map size generalization)."""

    def __init__(self, node_dim: int, edge_dim: int, hidden: int):
        super().__init__(aggr="mean")
        self.message_mlp = nn.Sequential(
            nn.Linear(2 * node_dim + edge_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden),
        )
        self.update_mlp = nn.Sequential(
            nn.Linear(node_dim + hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, node_dim),
        )

    def forward(self, x, edge_index, edge_attr):
        aggregated = self.propagate(edge_index, x=x, edge_attr=edge_attr)
        return x + self.update_mlp(torch.cat([x, aggregated], dim=-1))

    def message(self, x_i, x_j, edge_attr):
        return self.message_mlp(torch.cat([x_i, x_j, edge_attr], dim=-1))


class PolicyValueGNN(nn.Module):
    def __init__(self, node_in, edge_in, global_in, action_in,
                 hidden: int = 96, rounds: int = 3):
        super().__init__()
        self.node_encoder = nn.Linear(node_in, hidden)
        self.edge_encoder = nn.Linear(edge_in, hidden)
        self.rounds = nn.ModuleList(
            EdgeConv(hidden, hidden, hidden) for _ in range(rounds)
        )
        self.global_mlp = nn.Sequential(
            nn.Linear(hidden + global_in, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden),
        )
        # edge embedding for claim actions = concat of its endpoint nodes + edge enc
        self.edge_embed = nn.Linear(3 * hidden, hidden)
        self.policy_head = nn.Sequential(
            nn.Linear(2 * hidden + action_in, hidden), nn.ReLU(),
            nn.Linear(hidden, 1),
        )
        self.value_head = nn.Sequential(
            nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, 1),
        )

    def forward(self, batch):
        h = F.relu(self.node_encoder(batch.x))
        e = F.relu(self.edge_encoder(batch.edge_attr))
        for conv in self.rounds:
            h = conv(h, batch.edge_index, e)

        # mean-pool readout per graph
        from torch_geometric.utils import scatter
        pooled = scatter(h, batch.batch, dim=0, reduce="mean")
        g = self.global_mlp(torch.cat([pooled, batch.globals_], dim=-1))

        # per-action logits: action rows index their graph via batch.action_graph
        src, dst = batch.edge_index
        edge_emb = self.edge_embed(torch.cat([h[src], h[dst], e], dim=-1))
        zero_edge = torch.zeros_like(edge_emb[:1])
        edge_lookup = torch.cat([edge_emb, zero_edge], dim=0)   # -1 -> zero row
        act_edge = batch.action_edge.clone()
        act_edge[act_edge < 0] = edge_lookup.shape[0] - 1
        action_repr = torch.cat(
            [edge_lookup[act_edge], g[batch.action_graph], batch.action_feats],
            dim=-1,
        )
        logits = self.policy_head(action_repr).squeeze(-1)
        value = torch.sigmoid(self.value_head(g)).squeeze(-1)
        return logits, value

    @staticmethod
    def policy_loss(logits, action_graph, labels_flat):
        """NLL of the chosen action under a per-menu softmax."""
        probs = segment_softmax(logits, action_graph)
        return -torch.log(probs[labels_flat] + 1e-9).mean()
```

Batching contract (IMPORTANT): `batch.action_edge` arrives with **global**
edge indices and `-1` sentinels already resolved by Task 5's custom
collate. Do NOT let PyG's `__inc__` offset `action_edge` — `__inc__` adds
the offset to every entry, so any sentinel (`-1` or a `0`-means-none
scheme alike) turns into a valid-looking index into another graph's edges
after batching. The collate step computes offsets explicitly and leaves
`-1` untouched; the model maps `-1` to the appended zero row as written.

- [ ] **Step 2: Import smoke** — `uv run python -c "from operations.research.gnn.model import PolicyValueGNN; print('ok')"` (add `operations/research` to `sys.path` or run as module; the train CLI in Task 5 handles paths — a plain import check via `uv run python -c "import importlib.util, pathlib; ..."` mirroring the test files is fine).
- [ ] **Step 3: Commit** — `feat(research): PyG policy/value GNN encoder`.

## Task 5: Training + held-out-map evaluation

**Files:** Create `operations/research/gnn/train.py`.

- [ ] **Step 1: Implement the loader + loop** (key excerpts — write the full file):

```python
"""Train the policy/value GNN on DecisionRecords.

    uv run python operations/research/gnn/train.py --train-maps classic --eval-maps europe
    uv run python operations/research/gnn/train.py --train-maps classic,europe --eval-maps classic,europe --holdout-frac 0.1
"""
# path bootstrap: same REPO/applications/integrations inserts as
# bot_lab.py, PLUS the research dir itself (train.py lives one level
# deeper, so `import tensorize` needs it):
#   sys.path.insert(0, str(REPO / "operations" / "research"))
import json, argparse, time
import numpy as np
import torch
from torch_geometric.data import Data, Batch
from torch.utils.data import DataLoader

import tensorize  # loaded via importlib next to this file's parent


class DecisionData(Data):
    def __inc__(self, key, value, *args, **kwargs):
        if key == "action_edge":
            return 0            # NEVER auto-offset: -1 sentinels would corrupt
        if key == "label":
            return self.action_feats.shape[0]   # offset by action count
        if key == "action_graph":
            return 1
        return super().__inc__(key, value, *args, **kwargs)


def collate(data_list):
    """Batch, then resolve action_edge to global indices ourselves,
    preserving -1 sentinels (see the batching contract in model.py)."""
    batch = Batch.from_data_list(data_list)
    offsets, total = [], 0
    for d in data_list:
        offsets.append(total)
        total += d.edge_attr.shape[0]
    pieces = []
    for d, offset in zip(data_list, offsets):
        e = d.action_edge.clone()
        e[e >= 0] += offset
        pieces.append(e)
    batch.action_edge = torch.cat(pieces)
    return batch


def to_data(sample) -> DecisionData:
    d = DecisionData(
        x=torch.from_numpy(sample["node_feats"]),
        edge_index=torch.from_numpy(sample["edge_index"]),
        edge_attr=torch.from_numpy(sample["edge_feats"]),
    )
    d.globals_ = torch.from_numpy(sample["globals"]).unsqueeze(0)
    d.action_feats = torch.from_numpy(sample["action_feats"])
    d.action_edge = torch.from_numpy(sample["action_edge"])
    d.action_graph = torch.zeros(sample["action_feats"].shape[0], dtype=torch.long)
    d.label = torch.tensor([sample["label"]])
    d.won = torch.tensor([sample["won"]])
    return d
# main loop essentials:
#  - filter decisions.jsonl to decision == "turn"; a GAME is keyed by
#    (state.map_name, seed) — never plain seed (corpora may share seed
#    ranges). Split train/eval by state.map_name per
#    --train-maps/--eval-maps, plus --holdout-frac of train GAME KEYS for
#    same-map validation (all decisions of a game stay on one side)
#  - topo cache: {map_name: tensorize.MapTopology.load(map_name)}
#  - DataLoader(list_of_Data, batch_size=256, shuffle=True, collate_fn=collate)
#  - model.to("cuda"); AdamW(lr=3e-4, weight_decay=1e-4); 20 epochs
#  - loss = policy_loss + 0.5 * BCE(value, won)
#  - each epoch: report train loss, eval top-1 accuracy, eval NLL,
#    uniform-menu baseline accuracy (1/len(menu) averaged), value accuracy
#  - save weights: torch.save(model.state_dict(), RESULTS_DIR / "gnn_policy_v1.pt")
#    plus a JSON sidecar with tensor dims + training config
```

Write the full file (the sketched sections are mechanical); no other file changes.

- [ ] **Step 2: Overfit check** (catches wiring bugs before burning GPU time): train on 200 samples for 50 epochs — top-1 accuracy on those same samples must exceed 0.9. If it can't overfit, the batching offsets are wrong (check `__inc__` first).

- [ ] **Step 3: The two real runs.**

```powershell
uv run python operations/research/gnn/train.py --train-maps classic --eval-maps europe
uv run python operations/research/gnn/train.py --train-maps classic,europe --eval-maps classic,europe --holdout-frac 0.1
```

Success criteria: same-map holdout top-1 well above the uniform baseline (menus average ~40 actions, so uniform ≈ 2-3%; imitation of a deterministic-ish bot should reach 40-60%); the interesting *result* is the classic→europe transfer gap — record both numbers in the commit message.

- [ ] **Step 4: Commit** — `feat(research): GNN policy/value training with held-out-map evaluation`.

## Deferred to v2 (do NOT build in this plan)

- **Full decision coverage:** `draw_second` (schema-compatible today, but distribution-shifted) and `keep_tickets`, which needs real action features first: kept count, total value, cheapest-path distance of each offered ticket, overlap with current planned routes, endpoint reuse, value-per-distance.
- **GnnBot:** only after full decision coverage — a bot that ranks keep menus with an untrained head would fault its way through setup. When built: `ActionBot` mirroring `decision_export.symbolic_state` from the live view, cached `MapTopology`, CPU inference, `legal_actions[0]` fallback when torch is absent so the Mac-side loader never breaks.
- **Surrogate map critic:** trains on `map_profiles.jsonl` reusing this plan's encoder — separate plan.

---

## Self-review notes

- **Scope:** v1 is training-only on turn decisions; GnnBot, keep-tickets features, and the surrogate critic are explicitly v2+ (see Deferred section). This plan ends with a trained, evaluated policy/value model and the classic<->europe transfer numbers.
- **Known risks:** (1) torch/PyG API drift — the model uses only stable APIs (`MessagePassing`, `utils.softmax`, `utils.scatter`); (2) batching offset bugs — `action_edge` is exempted from `__inc__` and resolved in a custom collate (both `-1` and `0` sentinel schemes corrupt under `__inc__`, which offsets every entry), plus the Task 5 overfit check; (3) `torch_geometric.utils.scatter` exists from PyG 2.3+, no compiled extensions needed.
- **Type consistency:** `tensorize` dims (`NODE_DIM=6`, `EDGE_DIM=20`, `GLOBAL_DIM=28`, `ACTION_DIM=16`) are consumed by `PolicyValueGNN(node_in, edge_in, global_in, action_in)` in Task 5's construction; `action_edge=-1` maps to the zero edge row in the model; `DecisionData.__inc__` leaves `action_edge` unoffset (returns 0) — the custom collate offsets non-negative entries — and covers `label` (action count) and `action_graph` (1).
