# Mixed Route Costs — Design

**Date:** 2026-07-15
**Status:** Approved design, pending implementation plan
**Prepares for:** ferries and tunnels (mechanics themselves out of scope here)

## Problem

Routes today cost `length` cards of a single color (`X` = gray, any uniform
color), with locomotives wild. Ferries and tunnels need richer costs: a route
might cost 3 Blue + 2 Red, or 3 Grey + 2 Green, or 2 (Green or Blue), or
2 Locomotives + 3 Blue. The engine, map schema, action space, and board
rendering all assume one color per route.

## Cost model

A route's cost is an ordered list of **components**. Each component is
`CostComponent(count: int, options: tuple[str, ...])`, a frozen dataclass on
`Route.cost: tuple[CostComponent, ...]`.

`options` is normalized to exactly one of:

| Shape | Meaning |
|---|---|
| `("R",)` — one real color | `count` cards of that color |
| `("G", "U")` … n distinct real colors | `count` cards of **one** color chosen from the set |
| `("X",)` — grey, always alone | `count` cards of one uniform color, player's choice of all 8 |
| `("L",)` — locomotives, always alone | `count` spaces that must be paid with locomotives |

Real color letters are the deck's: `W B U G Y O R P` (plus `L` locomotive,
`X` grey). Grey is just the either-or over all 8 colors; a fixed color is the
either-or over 1. One payment rule covers everything.

### Payment semantics

- **Uniform color per segment:** each color component is paid in exactly one
  concrete color chosen from its options. For `3(G|B) + 2(G|R)` the legal
  color payments are exactly `5G`, `3G+2R`, `3B+2G`, `3B+2R` — never `2B+1G`
  inside a segment.
- **Segments choose independently.** `1U+1R+1Y+1(R|B)` (blue, red, yellow,
  red-or-black) may be paid `1U+1R+1Y+1B`; nothing couples the `(R|B)` choice
  to the earlier `R`.
- **Locomotives are wild everywhere:** an `L` card substitutes for any card in
  any component. An `L` component is therefore equivalent to a **minimum
  locomotive count** on the whole payment: `2L+3U` accepts `2L+3U`, `3L+2U`,
  `4L+1U`, `5L` — any payment with ≥ 2 locomotives whose remainder is Blue.
- Choosing the same concrete color for two components just requires enough
  total cards of it.

### Load-time validation (fail fast, error names the CSV row)

1. Component counts sum to `route.length` (spaces placed = length).
2. Distinct **real** colors mentioned anywhere in the cost ≤ `route.length`.
3. `X` never appears inside a multi-option set — `3(X|U)` is "basically just
   grey" and must be declared `3X`.
4. `L` never appears inside a multi-option set — `(L|U)` is meaningless when
   `L` is already wild.
5. Option-set letters are distinct, real colors; counts are positive.

### Legacy compatibility

- Loader synthesizes `cost = (CostComponent(length, (color,)),)` when no cost
  is declared — existing maps behave byte-identically (proven, see Testing).
- **Every route is stored uniformly as its cost array** — a classic route is
  simply the one-segment case. There is no "mixed" marker/sentinel; nothing
  branches on mixed-vs-classic, consumers just read `cost` (engine) or
  `data.segments` (display).
- `Route.color` survives as a **derived legacy convenience** for
  one-component routes only (the single letter, `"X"` for grey). Consumers
  that still read it are exactly the ones that can only ever see
  one-component routes; anything that can meet a multi-component route reads
  `cost` / `payment_colors()` instead (see Bot payment choice).
- The existing unenforced `Route.locomotives` (ferry minimum) and
  `Route.is_tunnel` fields stay exactly as they are — ignored. Ferry minimums
  will be declared as `Cost` terms (e.g. `2L+3X`) when ferries land. Enforcing
  the old column now would silently change behavior on maps that carry it.

## CSV schema

New optional `Cost` column. Grammar: `+`-separated terms, each
`<count><spec>`:

```
Cost := term ("+" term)*
term := INT spec
spec := LETTER            # one of W B U G Y O R P X L
      | "(" LETTER ("|" LETTER)+ ")"   # 2+ distinct real colors
```

Examples: `3U+2R`, `3X+2G`, `2(G|U)`, `2(G|U|R)`, `3L`, `2L+3U`.
Missing/empty `Cost` → synthesized from `Distance` + `Color` as today.

## Action space

`ClaimRoute` keeps `(route_id, color, locomotives)` unchanged and gains
`payment: tuple[tuple[str, int], ...] | None = None` — one
`(chosen_color, locomotives_substituted)` pair per component, in cost order
(`L` components appear as `("L", n)` with `n ≥ count`).

- `payment=None` means single-component; execution derives it from
  `color`/`locomotives` exactly as today.
- Missing fields still default when loading old in-memory action dictionaries;
  new single-component records may serialize an additive `payment: null`.
- Legal-menu enumeration validates payment shape and affordability.
  `Player.__apply_claim` trusts menu membership and spends the selected
  payment; bots cannot inject an action outside that menu.

## Enumeration core (`actions.py` — the hot path)

`enumerate_claim_actions` / `affordable_route_options` generalize to iterate
per-component color choices × locomotive splits. Constraints:

- The single-component path must preserve today's exact action **ordering**
  (including gray-route iteration over hand insertion order) — the existing
  `AffordabilityParityTests` oracles must pass unchanged.
- Single-component actions keep `payment=None`. Serialized actions may gain
  an additive `payment: null` field; stored-game byte compatibility is not a
  requirement for this migration and the database may be rebuilt.
- Actions are **deduplicated by the actual card multiset spent**: two
  component-assignments that burn the same cards are the same choice; one
  canonical action represents them.
- `affordable_route_options` still returns `(route, min_locos)` pairs, where
  `min_locos` is the minimum over legal payments — bots keep working without
  modification and stay legal on mixed maps automatically.
- Branching is bounded: option sets ≤ 8 ≈ today's gray-route enumeration.

## Bot payment choice

"How do I pay?" is action selection, not a new interface — today's gray
routes already surface payment choice as multiple `ClaimRoute` actions (one
per color), and bots rank them (`min(candidates, key=(needs[a.color],
-hand[a.color]))`). Mixed routes extend the same seam:

- **Choice surface:** every distinct legal payment of a mixed route appears
  as its own `ClaimRoute` action (with `payment` filled) in
  `legal_claim_actions`. A bot that ranks claim actions today automatically
  gets the full menu of payments.
- **Valuation hook:** a helper `claim_spend(action, route) -> Counter`
  (actions.py) returns exactly which cards an action burns — derived from
  `payment`, or from `color`/`locomotives` + route length when `payment` is
  `None`. Bots rank payments by scoring that Counter with their own needs
  weights; the engine never imposes a preference (same structure-vs-weights
  boundary as the culled-map caches: engine enumerates what is legal, bots
  decide what is good).
- **Planning shim:** the bots' `colors = [route.color] if route.color != "X"
  else ALL` sites become `route.payment_colors()` — the union of all option
  colors across components (grey → all 8). For one-component routes this
  reduces to exactly today's expression, so existing-map behavior is
  unchanged (parity-checked). On mixed routes the planners' color-stack
  logic stays coherent without crashing.
- **Deferred:** smarter per-payment valuation (which payment preserves the
  best future hand) lands with the scoring/strategy round. This round only
  guarantees bots see every option, can rank by spend, and never crash.

Supported planners in this round are Qualifier and Example; Random already
chooses directly from the legal menu. Fable and Codex Best support is deferred.

## ML features

The existing route-color feature remains stable for classic routes. Mixed
routes add explicit structural features instead of being collapsed into grey:
component count, option-set count, grey-space count, required-locomotive-space
count, distinct mentioned real colors, and total declared real-color options.
Per-color eligible-space counts are also emitted for all eight real colors.

## Rendering

### Per-segment board rendering

`board_view.py` precomputes a render spec per train space, Python-side, in
component order: `data.segments = [{kind, colors}]` with one entry per
rectangle, `len == route.length`. **Every route gets `data.segments`** — a
classic route is just `length` identical solid entries — so the painter has
one uniform path and no mixed-vs-classic branch. (The widget keeps a
fallback to `link.color` only for stored payloads produced before this
change.)

| Cost shape | Rectangle rendering |
|---|---|
| fixed color | solid, as today |
| 2 options | cut into 2 triangles along the diagonal, one option color each |
| n ≥ 3 options | n diagonal stripes (the triangle look, generalized) |
| grey (`X`) | solid grey (validation guarantees grey never appears in a set) |
| `L` | rainbow-gradient fill |

Claimed-route rendering (owner's inset rectangle + translucent band) is
unchanged and draws over whatever the base segments are. Routes without
`data.segments` (older stored payloads) fall back to today's single-color
rendering.

### Shared locomotive gradient

The locomotive look changes from flat `#17becf` to a rainbow
`red → orange → yellow → green → blue → indigo → violet`. It lives in the
shared color config (`board_view.py`) as **gradient stops**, not a CSS
string, because each renderer materializes it differently:

- card faces (info bar): CSS `linear-gradient(to right, …)`
- market pie: SVG `<linearGradient>` def referenced by slice `fill`
- board canvas: `ctx.createLinearGradient` across the rectangle

One definition; every widget that shows `L` updates together. Payload carries
the stops; widgets tolerate the old flat-string form for stored games.

## Testing

- **Grammar/validation unit tests:** every guard above, good and bad rows.
- **Payment enumeration unit tests** on crafted hands: mixed, either-or
  (uniform-per-segment enforced), grey, `L` floors, locomotive substitution,
  same-color-two-components.
- **Parity, two ways:** `AffordabilityParityTests` (embedded old-behavior
  oracles) pass unchanged, and `operations/research/profile_engine.py
  --parity-dump` before/after stays byte-identical on existing maps.
- **Integration:** a small hand-written mixed-cost test map played end-to-end
  (claim mixed routes via engine), plus a live widget probe validating
  `data.segments` shape and the culled-map path.
- **Perf:** re-run `profile_engine --profile`; the generalized enumeration
  must not regress the ~0.38 s/game baseline meaningfully.

## Out of scope (explicitly deferred)

- **Scoring rebalance** — mixed routes may be easier/harder to claim than
  their length suggests; revisit points tables later (user-deferred).
- Ferry and tunnel **mechanics** (tunnel card flips, enforcing loco minimums
  from the legacy column).
- Map **generator** emitting mixed costs.
- Bot **strategic** awareness of payment flexibility (they stay legal via the
  shared enumeration; valuation comes with scoring).
