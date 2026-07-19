# Structured Bot Decisions and Legal Options — Design

**Date:** 2026-07-19
**Status:** Design (revised from discussion draft; compatibility machinery removed)
**Replaces:** The flat `act(view, legal_actions)` bot contract
**Prepares for:** tunnel resolution and other multi-step actions with intermediate information

## Purpose

The engine currently gives a bot a fresh `PlayerView` and a flat list of legal
`Action` objects for every decision. This is safe and complete, but it makes
common queries require repeated list scans, identifies phases with bare
strings, and silently substitutes a legal action when a bot returns an illegal
one — hiding bot bugs until the board state looks wrong turns later.

This design has two goals, in order:

1. **Developer experience and logical flow.** A bot author should navigate a
   turn the way a human describes it, get autocomplete that reflects what is
   actually possible in the current phase, and get a loud, specific error the
   moment their bot misbehaves.
2. **A clean seam for tunnels** and other multi-step actions that reveal
   information mid-turn.

```python
decision.claims[3].payments
decision.claims.by_route_id["Seattle-Portland-1"].payments
decision.draws.face_up[2]
decision.draws.blind
decision.destination_tickets.draw
```

After the bot selects an action, the engine applies it. If that action reveals
new information without ending the turn, the engine sends a new `Decision`
with an updated state and a new phase-scoped option menu. The engine does not
ask bots to predict unknown cards or submit a contingent plan in advance.

The design recovers the intuitive hierarchy of the historical
`choose_turn_action` / `choose_route_to_claim` / `choose_color_to_spend`
interface without restoring its engine-level callback chain. A bot may split
its own reasoning into "what kind of action?", "which route?", and "how do I
pay?" helper methods, but it returns one complete canonical leaf action to the
engine whenever no new information was revealed between those questions.

## Scope decision: no backward compatibility

Every bot in existence lives in this repository and is maintained by its
author. Therefore:

- The `act(view, legal_actions)` contract is **replaced**, not bridged. All
  in-repo bots, the template, and the tests migrate in the same branch that
  introduces `decide(decision)`. There is no engine-side dispatch shim and no
  `LegacyBotAdapter` retention plan.
- The bot API sidecar's choose-method wire protocol
  (`ClaimRouteRequest`, `DrawTrainRequest`, `ChooseColorRequest`, …) is
  **deleted** and replaced by a decision-envelope protocol. Every sidecar is
  ours; there is nothing to negotiate with. The envelope carries a
  `schemaVersion` field as cheap insurance, with no fallback path.
- Stored research data (decision exports, xG datasets) is regenerable and gets
  **regenerated** on the new schema rather than preserved in parallel shapes.

What survives from the old system is kept on its merits, not for
compatibility: `decision.actions` (the flat canonical tuple) remains because
random bots, ML scoring, and replay verification genuinely want it, and the
deterministic enumeration order remains because seeded-replay determinism is a
correctness property the research pipeline depends on.

## Current system

### Bot contract

Bots implement:

```python
act(view: PlayerView, legal_actions: list[Action]) -> Action
```

The list contains frozen dataclass instances: `Pass()`, `DrawBlind()`,
`DrawFaceUp(index, card)`, `ClaimRoute(route_id, color, locomotives, payment)`,
`DrawTickets()`, `KeepTickets(indices)`.

There is no index by action type, route ID, or market position. Bots obtain
submenus with linear scans. `Player.__choose` accepts the returned action when
`action in legal_actions` — dataclass equality is value-based, so an equal
reconstructed action passes even if it is not the object from the list. An
illegal return is silently replaced by the first legal action.

### Current decision sequence

One game turn may call `act` more than once:

```text
start turn
    |
    v
decision="turn"
    |-- claim route ------------------------------> end turn
    |-- draw face-up locomotive -----------------> end turn
    |-- draw a train card
    |       |
    |       v
    |   engine mutates hand/market/deck
    |       |
    |       v
    |   decision="draw_second" ------------------> end turn
    |
    `-- draw destination tickets
            |
            v
        engine reveals offer
            |
            v
        decision="keep_tickets" -----------------> end turn
```

The engine builds a fresh `PlayerView` for each box. The second draw sees the
first card in the bot's hand and the refilled market. The ticket decision
receives the revealed tickets in `view.ticket_offer`. Initial setup uses the
same `keep_tickets` phase with a minimum keep of two; a turn-time draw uses a
minimum keep of one.

### What must be preserved

- The engine is the sole source of legality; illegal bot behavior cannot
  mutate the game.
- Each chance outcome is resolved before the bot makes the next decision.
- Leaf actions are compact, serializable, deterministic, and replayable.
- A random bot is a one-liner.

### What must be fixed

- Every bot reimplements grouping by type and route.
- `view.decision` strings, `view.ticket_offer`, and bot memory collectively
  describe the phase; no single object describes the complete decision.
- A second-draw callback does not say which first draw produced it.
- Illegal returns are silently substituted — the single worst debugging
  property of the current system. A buggy bot plays a wrong move and keeps
  going.
- Equality membership does not prove a returned action came from the current
  menu, and a delayed remote response from an earlier phase could be applied
  to a later one.
- Extending `view.decision` with tunnel strings would spread another round of
  branching and list filtering through every bot.

## Design principles

### 1. Callback only when information changes

The engine creates a new decision only when it has mutated the state or
revealed information that can change the bot's choice. Questions that can be
answered from the same information belong to one bot callback.

| Choice sequence | Engine callbacks | Reason |
|---|---:|---|
| choose claim vs draw vs tickets | 1 | all alternatives are already known |
| choose a route, then choose its payment | 1 | payment options are already known |
| choose a first train card, then a second | 2 | applying the first draw changes the hand and possibly the market |
| take a face-up locomotive | 1 | it ends the turn immediately |
| draw tickets, then choose which to keep | 2 | the offer was unknown |
| attempt a tunnel, then pay or decline | 2 | the tunnel reveal creates a surcharge |

This separates two concepts the historical interface conflated:

- **Navigation hierarchy:** how a bot organizes and searches choices it can
  already see. Lives *inside* a decision.
- **Temporal decision phases:** places where the engine must stop because a
  chance result or state transition changes what the bot knows. Separate
  decision objects.

### 2. Fail loudly

An illegal return from a bot is a bot bug, and the system's job is to point at
it immediately:

- In notebooks, spectate, and direct engine use, an illegal return **raises**
  with a message naming the decision type, what was returned, and the legal
  menu.
- In managed matches, where robustness matters, the existing substitution
  behavior remains — but it logs at ERROR with the same detail and counts as a
  runtime failure in the seat's aggregate results, so it is visible in the
  dashboard rather than silent.

### 3. Exhaustiveness by tooling

`BotDecision` is a typed union dispatched with `match`. With pyright (already
configured in this repo), adding `TunnelDecision` to the union produces a
type-check error in every bot whose `match` does not handle it. The
"adding tunnels does not add tunnel conditionals to ordinary turn parsing"
property is enforced by the type checker, not by discipline.

## Proposed system

### Bot contract

```python
def decide(self, decision: BotDecision) -> Action:
    ...
```

The public union initially contains:

```python
BotDecision = TurnDecision | SecondDrawDecision | KeepTicketsDecision
```

Every decision has:

```python
class Decision(Protocol):
    decision_id: DecisionId
    state: PlayerView
    actions: tuple[Action, ...]
```

`state` is everything the player may know now. `actions` is the flat tuple of
canonical selectable leaves — the generic surface for random bots, ML scoring,
replay verification, and logging. The concrete decision type provides the
intuitive hierarchy and phase-specific context. Inapplicable categories do not
appear as empty properties, so autocomplete describes what is actually
possible in that phase.

### Decision identity

```python
@dataclass(frozen=True)
class DecisionId:
    round_number: int
    turn_index: int
    phase_index: int   # 0 = turn, 1 = follow-up (second draw / keep tickets / tunnel)
```

Decision IDs are **derived from game position, not from a counter**, so
identical seeded games produce identical IDs regardless of threading. They are
unique per (match, seat), totally ordered within a turn, logged with the
chosen action, and used to reject stale remote responses.

### Turn decision

```python
@dataclass(frozen=True)
class TurnDecision:
    decision_id: DecisionId
    state: PlayerView
    draws: DrawOptions
    claims: ClaimOptions
    destination_tickets: DrawTicketOptions
    pass_action: Pass | None
    actions: tuple[Action, ...]
```

This recovers the old top-level question without making it a separate engine
callback:

```python
def decide_turn(self, decision: TurnDecision) -> Action:
    mode = self.choose_action_type(decision)
    if mode == "claim":
        route = self.choose_route(decision.claims)
        return self.choose_payment(route.payments)
    if mode == "draw":
        return self.choose_card(decision.draws)
    if mode == "tickets":
        return decision.destination_tickets.draw
    return decision.pass_action
```

`choose_action_type`, `choose_route`, `choose_payment`, and `choose_card` are
ordinary bot helper methods operating on one immutable decision. The engine
receives only the final leaf.

`pass_action` is `None` whenever any other action is legal (pass appears only
as the sole remaining choice, matching today's enumeration). The docstring
must state this — `return decision.pass_action` is only valid when the bot has
established nothing else is available.

#### Train-card draws

```python
@dataclass(frozen=True)
class DrawOptions:
    blind: DrawBlind | None
    face_up: FaceUpDrawIndex
```

Market lookup retains actual market positions. A face-up locomotive is illegal
for the second draw, so compacting legal choices would make indexes
misleading:

```python
decision.draws.face_up[2]          # market slot 2, or None if unavailable
decision.draws.face_up.available   # all legal DrawFaceUp leaves
decision.draws.blind               # DrawBlind() or None
```

#### Route claims and payments

```python
@dataclass(frozen=True)
class RouteClaimOptions:
    route: Route
    payments: tuple[ClaimRoute, ...]


class ClaimOptions(Sequence[RouteClaimOptions]):
    by_route_id: Mapping[str, RouteClaimOptions]
```

Each claimable route appears once. Its `payments` are all legal ways to pay
for that route, in the deterministic order produced by today's enumeration:

```python
route_choice = decision.claims.by_route_id[target_route_id]
payment = max(route_choice.payments, key=payment_utility)
return payment
```

Indexing `claims[3]` means the fourth currently claimable route, not the
fourth route on the map. Stable plans should use `by_route_id`; sequence
access exists for ranking and display. The name `claims` distinguishes these
currently legal choices from `decision.state.routes`, which contains every
route on the board.

#### Destination-ticket draw

```python
@dataclass(frozen=True)
class DrawTicketOptions:
    draw: DrawTickets | None
```

Only the known choice to request an offer. The unknown offer is not
represented until the engine deals it.

### Second-draw decision

```python
@dataclass(frozen=True)
class DrawResult:
    action: DrawBlind | DrawFaceUp
    card: str


@dataclass(frozen=True)
class SecondDrawDecision:
    decision_id: DecisionId
    state: PlayerView
    first_draw: DrawResult
    draws: DrawOptions
    actions: tuple[Action, ...]
```

It has no `claims` or `destination_tickets` property because those choices are
not legal in this phase. The updated `state` contains the drawn card in the
hand and the refreshed market; `first_draw` makes the transition explicit.

For a face-down draw, `first_draw.card` is private information included only
in the acting player's decision. **Any serialization of decision envelopes —
export, replay tooling, spectator views — must scrub `first_draw.card` for
non-acting seats.** A face-up locomotive ends the turn and produces no
`SecondDrawDecision`.

### Keep-ticket decision

```python
@dataclass(frozen=True)
class KeepTicketsDecision:
    decision_id: DecisionId
    state: PlayerView
    source: Literal["setup", "turn"]
    offer: tuple[DestinationTicket, ...]
    minimum_to_keep: int
    choices: KeepTicketOptions
    actions: tuple[KeepTickets, ...]
```

The offer and its rule belong to this phase rather than as optional fields on
every `PlayerView` (which drops `ticket_offer` from the view entirely):

```python
decision.offer
decision.minimum_to_keep
decision.choices.available
decision.choices.by_indices[(0, 2)]
```

### Immutability

Decisions are shared across a bot's helper methods and logged after the fact,
so they must be deeply immutable in practice: frozen dataclasses whose fields
are frozen dataclasses, tuples, or immutable mappings (`by_route_id` built
once as a `MappingProxyType` or equivalent). A test enforces this
(see Tests).

### Legality and trust

Every leaf in `decision.actions` and every leaf reachable through its grouped
properties is created by the engine. Selection resolves through one
decision-local table:

- **In-process bots** return the canonical leaf object. The engine checks
  membership by **identity** (`id(leaf)` in the decision's table), not value
  equality. Value-equality acceptance is removed — a reconstructed action is
  an illegal return and fails loudly per design principle 2.
- **Remote bots** receive one `selectionId` per leaf and respond with
  `(decisionId, selectionId)`. The engine maps the pair back to the canonical
  object and rejects a stale `decisionId` outright.

`actions` must contain each selectable leaf exactly once and preserve the
current deterministic ordering:

1. blind draw;
2. face-up draws in market order;
3. route payments in map-route and payment-enumeration order;
4. destination-ticket draw;
5. pass when it is the only choice.

Keep-ticket and future tunnel decisions preserve their own enumeration order.

### Template as the teaching surface

There is no `HierarchicalBot` base class. The `match` dispatch is eight lines
and teaching it directly in the template is worth more than hiding it:

```python
def decide(self, decision: BotDecision) -> Action:
    """Choose one canonical action exposed by the current decision."""
    match decision:
        case TurnDecision():
            return self.choose_turn(decision)
        case SecondDrawDecision():
            return self.choose_second_card(decision)
        case KeepTicketsDecision():
            return self.choose_tickets(decision)
```

The template must remain runnable without edits and show both paths a new
author needs:

```python
random.choice(decision.actions)          # simplest complete bot
decision.claims[0].payments[0]           # hierarchical turn navigation
```

Its comments explain: a bot returns a leaf supplied by the engine,
`decision.actions` is always the generic escape hatch, and a new decision
arrives after a draw or offer changes the available information. The template
never reconstructs action dataclasses or inspects private engine state.

### Docstrings

All new public decision APIs require substantial docstrings in the same
commit that introduces them. At minimum, document:

- every concrete decision class: when the engine emits it and what preceded
  the phase;
- every grouped option/index class: sequence ordering, stable lookup keys, and
  whether an unavailable lookup returns `None` or raises;
- `decision_id`, `state`, and `actions`: visibility, immutability,
  canonical-leaf, and deterministic-order guarantees;
- `DrawResult`, especially the privacy of a face-down card;
- actual market-index semantics for `face_up[index]`;
- claim-versus-map-route semantics and payment ordering;
- setup-versus-turn ticket minimums and the `pass_action` only-choice rule;
- the `decide` contract and the illegal-return behavior per context;
- future `TunnelDecision` fields and atomic commit/decline behavior when that
  type is implemented.

Class docstrings include a compact usage example where navigation is not
obvious. Method and property docstrings describe return values and
empty/unavailable behavior rather than restating the name.

## Tunnel groundwork

The structured menu does not implement tunnel rules by itself. It creates the
decision boundary needed to implement them without overloading `ClaimRoute`
or asking the bot to predict a random reveal.

```text
TURN decision
    |
    | choose a tunnel route and initial ClaimRoute payment
    v
engine reveals the tunnel cards and computes the surcharge
    |
    | surcharge == 0
    +----------------------------------------------> commit claim
    |
    | surcharge > 0
    v
TunnelDecision
    |-- choose an additional payment -------------> commit claim atomically
    `-- decline -----------------------------------> return initial cards; end turn
```

```python
TunnelDecision(
    decision_id=decision_id,
    state=state_after_reveal,
    route=route,
    initial_payment=claim_action,
    revealed_cards=("U", "L", "R"),
    surcharge=2,
    additional_payments=(...),
    decline=DeclineTunnel(),
    actions=(...),
)
```

Tunnel implementation requires a transactional claim path. Today's
`Player.__apply_claim` spends cards and claims the route immediately. A tunnel
claim must retain the initial payment as pending intent, reveal cards, and
then either commit the initial and additional payments together or decline
without spending the initial payment. Revealed tunnel cards follow the tunnel
discard rules. With a seeded deck and logged response action, replay remains
deterministic.

## Migration surface

### Engine

- New focused module `services/native-runtime/src/ticket_to_ride/engine/decisions.py`
  for the decision and grouped-option types; `actions.py` keeps only leaves.
- Keep the existing legal enumeration functions; group their output without
  changing order or legality.
- `Player.__choose` constructs the appropriate decision type and calls
  `decide`; illegal returns raise (or, under managed execution, substitute +
  ERROR log + runtime-failure count).
- Draw application returns a `DrawResult` for `SecondDrawDecision.first_draw`.
- `ticket_offer` and minimum-keep metadata move off `PlayerView` onto
  `KeepTicketsDecision`.
- Canonical leaf actions continue to be logged, so existing deterministic
  replay records remain conceptually valid.

Primary files: `engine/actions.py`, `engine/player.py`,
`engine/state/views.py`, new `engine/decisions.py`.

### Bots and template

All in-repo bots (Random, Example, Qualifier, Fable Best, Codex Best, Bayesian
Utility, XG Bot), the test bots, the runtime CLI bootstrap path, and
`integrations/external/templates/bots/build_your_bot_here.py` (plus
`quality/tests/test_bot_template.py` and bot-author docs) migrate to `decide`
in the same branch. Random-style bots use `decision.actions`; planners use the
grouped properties; XG Bot keeps scoring flattened leaves until a grouped
model is desired.

### Wire protocol v2 (sidecar + managed execution)

`ManagedSeatInterface` and `BotExecutor` forward a serialized decision
envelope instead of choose-method calls:

- request: `schemaVersion`, `decisionId`, concrete phase type, player-visible
  state, phase context, grouped options for navigation, one `selectionId` per
  canonical leaf;
- response: `(decisionId, selectionId)` — never a reconstructed action
  payload.

The choose-method endpoints and their request/response models are deleted.
Remote bots (bot connections) automatically speak v2 once their sidecar
updates; there is no mixed-version support.

### Replay, analysis, and ML

`GameRecord` keeps storing canonical actions; `ScriptedBot` implements
`decide` by returning its next scripted action, verified against
`decision.actions`. Decision export and xG tooling switch to the new schema
(concrete decision type + `decision_id` as new fields; `actions` remains the
flat array feature rows align to) and stored datasets are regenerated.
Grouped option metadata is **not** persisted — it is a pure function of
(state, actions) and would only bloat storage.

Affected: `engine/replay.py`, `operations/research/decision_export.py`,
`operations/research/xg_data_pump.py`, `operations/research/train_xg_bot.py`,
`integrations/external/ml/xgb_features.py`.

### Tests

During development, the lossless-view assertion is the scaffolding that
protects seeded-replay determinism:

```python
self.assertEqual(decision.actions, tuple(old_legal_actions))
```

It may be deleted once the old enumeration surface is gone. Contract tests
cover:

- claim sequence and `by_route_id` point to the same entries;
- each route payment appears exactly once;
- face-up indexes stay aligned to market slots;
- face-up locomotives are unavailable in the second-draw phase;
- phase-inapplicable properties are absent from the concrete decision type;
- `SecondDrawDecision` reports the first draw and revealed private card, and
  serialization scrubs the card for non-acting seats;
- setup and turn ticket offers report different minimum keeps;
- `pass_action` is `None` whenever another action is legal;
- decisions are deeply immutable (frozen dataclasses, tuple/immutable-mapping
  fields only);
- an illegal in-process return raises with the decision type and menu in the
  message; under managed execution it substitutes, logs at ERROR, and counts
  as a runtime failure;
- stale decision IDs and unknown selection IDs are rejected on the wire;
- identical seeded games produce identical `DecisionId` sequences;
- replay of existing seeded games is unchanged through the new dispatch;
- the updated template imports and completes a seeded game without edits, and
  its selected value always belongs to `decision.actions`;
- all public decision, option-index, and bot-contract types have non-empty
  docstrings.

## Migration sequence

### Phase 1 — Decision types, `decide` contract, all bots, template

One branch: introduce `decisions.py` with complete docstrings, construct
decisions from the existing legal action lists (order unchanged, proven by
the lossless assertion), switch `Player.__choose` to `decide`, implement the
loud-failure behavior, migrate every in-repo bot and the template, update
their tests. This is the only phase with real design risk; everything after
it is plumbing.

### Phase 2 — Wire protocol v2

Serialize the decision envelope through `BotExecutor` and the sidecar; add
selection-ID resolution and stale-decision rejection; delete the
choose-method endpoints, models, and `LegacyBotAdapter`.

### Phase 3 — Exports

Switch decision export and xG tooling to the new schema; regenerate stored
datasets and retrain if the current models are worth keeping (they are
regenerable; see the noise-floor findings).

### Phase 4 — Tunnels

Add `TunnelDecision` to the union (pyright then flags every bot that does not
handle it), the pending/atomic claim path, surcharge enumeration, decline
handling, logging, replay tests, and bot evaluation of the new response menu.
This phase does not change how turn, second-draw, or ticket decisions are
represented.

## Acceptance criteria

- Every currently legal action appears exactly once in `decision.actions`,
  and no illegal action appears.
- Existing seeded games replay identically through the new dispatch.
- A bot can find a route and all of its payments without scanning unrelated
  actions, and address a face-up card by its actual market index.
- Every follow-up decision carries the new state and explicit context for the
  information just revealed.
- The engine makes another callback only after state changes or information
  is revealed; route selection and payment selection remain one engine
  decision.
- The engine applies only a selection belonging to the current decision, and
  an illegal return fails loudly (raise in direct use; ERROR + substitution +
  runtime-failure count under managed execution).
- Simple bots remain simple: `random.choice(decision.actions)` is a complete
  bot.
- Adding `TunnelDecision` to the union produces pyright errors in unmigrated
  bots rather than silent misbehavior.
- The shipped template uses the new contract, remains runnable without edits,
  and teaches both `decision.actions` and hierarchical navigation.
- Every public decision and grouped-option type has a behavioral docstring;
  non-obvious indexes and phase transitions include examples.
- No choose-method wire endpoints, `act` entry points, or `LegacyBotAdapter`
  remain after Phase 2.

## Resolved design decisions

1. **Selection: identity in-process, IDs on the wire.** One decision-local
   table resolves both; value-equality acceptance is removed everywhere.
2. **`act` retirement: immediate.** No external bots exist; the contract is
   replaced in Phase 1 rather than bridged.
3. **Grouped metadata persistence: no.** Exports store the concrete decision
   type and `decision_id` alongside the flat actions; grouped structure is
   derived, not stored.
4. **`HierarchicalBot`: dropped.** The template teaches `match` dispatch
   directly; no second public contract to maintain.
