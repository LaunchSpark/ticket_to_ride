"""Route cost components and the mixed-cost grammar."""
import re
from dataclasses import dataclass
from typing import Tuple

CARD_COLORS: Tuple[str, ...] = ("R", "B", "U", "G", "O", "P", "W", "Y")
GREY = "X"
LOCOMOTIVE = "L"


class CostError(ValueError):
    """A cost expression violating the grammar or model guards."""


@dataclass(frozen=True)
class CostComponent:
    count: int
    options: Tuple[str, ...]

    def is_grey(self) -> bool:
        return self.options == (GREY,)

    def is_locomotive(self) -> bool:
        return self.options == (LOCOMOTIVE,)

    def concrete_options(self) -> Tuple[str, ...]:
        return CARD_COLORS if self.is_grey() else self.options


_TERM_RE = re.compile(r"(\d+)(?:([A-Z])|\(([A-Z](?:\|[A-Z])+)\))")


def parse_cost(spec: str, length: int) -> Tuple[CostComponent, ...]:
    components = []
    for term in spec.replace(" ", "").split("+"):
        match = _TERM_RE.fullmatch(term)
        if not match:
            raise CostError(f"unparseable cost term {term!r} in {spec!r}")
        count = int(match.group(1))
        options = ((match.group(2),) if match.group(2)
                   else tuple(match.group(3).split("|")))
        components.append(CostComponent(count, options))
    cost = tuple(components)
    validate_cost(cost, length, spec)
    return cost


def synthesize_cost(length: int, color: str) -> Tuple[CostComponent, ...]:
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
            raise CostError(f"invalid option letter(s) {bad} in {spec!r}")
    total = sum(component.count for component in cost)
    if total != length:
        raise CostError(f"cost {spec!r} totals {total}, route length is {length}")
    distinct = {letter for component in cost
                if not (component.is_grey() or component.is_locomotive())
                for letter in component.options}
    if len(distinct) > length:
        raise CostError(
            f"cost {spec!r} names {len(distinct)} distinct colors on a length-{length} route"
        )


def cost_to_str(cost: Tuple[CostComponent, ...]) -> str:
    terms = []
    for component in cost:
        options = (component.options[0] if len(component.options) == 1
                   else f"({'|'.join(component.options)})")
        terms.append(f"{component.count}{options}")
    return "+".join(terms)
