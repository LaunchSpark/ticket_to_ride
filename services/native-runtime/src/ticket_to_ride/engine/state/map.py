import csv
import heapq
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Dict, Optional, Set, Tuple


MAPS_DIR = Path(__file__).resolve().parents[6] / "operations" / "data" / "maps"
DEFAULT_MAP_NAME = "classic"


def available_maps() -> List[str]:
    """Return the names of every map CSV available under the maps directory."""
    return sorted(path.stem for path in MAPS_DIR.glob("*.csv"))


def resolve_map_path(map_name: Optional[str]) -> Path:
    """Resolve a map name to its CSV path, defaulting to the classic map."""
    resolved_name = map_name or DEFAULT_MAP_NAME
    map_path = MAPS_DIR / f"{resolved_name}.csv"
    if not map_path.exists():
        raise ValueError(f"Unknown map '{resolved_name}'. Available maps: {available_maps()}")
    return map_path

class Route:
    city1: str
    city2: str
    length: int
    color: str
    route_id: str
    route_label: str
    claimed_by: 'str | None'

    def __init__(self, city1: str, city2: str, length: int, color: str, route_id: str):
        """Represent a single route on the map."""
        self.city1 = city1
        self.city2 = city2
        self.length = length
        self.color = color
        self.route_id = route_id
        self.route_label = f"{self.city1.replace(' ', '_')}-{self.city2.replace(' ', '_')}-{self.color}"
        self.claimed_by = None

    def other_city(self, city: str) -> str:
        """Return the opposite endpoint of the route."""
        return self.city1 if self.city1 != city else self.city2

    def get_cities(self) -> 'set[str]':
        """Return a set containing both connected cities."""
        return {self.city1, self.city2}

    def sibling_group_key(self) -> tuple[tuple[str, str], int]:
        return (tuple(sorted((self.city1, self.city2))), self.length)
    
    def __repr__(self):
        return self.route_id

class _UnionFind:
    """Union-find over city names, used to track a player's merged network."""

    def __init__(self):
        self._parent: Dict[str, str] = {}

    def find(self, item: str) -> str:
        parent = self._parent.setdefault(item, item)
        if parent != item:
            self._parent[item] = self.find(parent)
        return self._parent[item]

    def union(self, a: str, b: str) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self._parent[root_a] = root_b

    def connected(self, a: str, b: str) -> bool:
        return self.find(a) == self.find(b)


def _route_claimable_by(
    route: Route,
    siblings: List[Route],
    claim_of: 'Callable[[Route], str | None]',
    player_id: Optional[str],
    player_count: int,
) -> bool:
    """The double-route claim rules, parameterized over where claims come from.

    `claim_of` abstracts the claim source so the same rules apply to the live
    board (route.claimed_by) and to reconstructed historical claims (a
    route_id -> player_id dict), keeping is_route_claimable and contract_map
    from ever drifting apart.
    """
    if claim_of(route) is not None:
        return False
    if not siblings:
        return True
    if player_id is not None and any(claim_of(sibling) == player_id for sibling in siblings):
        return False
    if player_count <= 3 and any(claim_of(sibling) is not None for sibling in siblings):
        return False
    return True


@dataclass
class CulledMap:
    """A player's view of the board with their network contracted.

    Cities joined by the player's own claims collapse into one merged node
    (id = member cities sorted and joined with "+"), and only routes the
    player could still actually claim survive. Connectivity/cost queries on
    this view answer "what would it take to connect X and Y from here?" -
    traveling through your own network is free.
    """

    player_id: str
    city_to_node: Dict[str, str]
    nodes: List[str]
    routes: List[Route]

    def endpoints(self, route: Route) -> Tuple[str, str]:
        """Return the merged-node endpoints of a surviving route."""
        return (self.city_to_node[route.city1], self.city_to_node[route.city2])

    def connected(self, city1: str, city2: str) -> bool:
        """True if the two cities are already joined by the player's claims."""
        return self.city_to_node[city1] == self.city_to_node[city2]

    def cheapest_connection(self, city1: str, city2: str) -> 'int | None':
        """Fewest trains needed to connect two cities through claimable routes.

        0 means already connected; None means impossible (cut off by other
        players' claims).
        """
        start, goal = self.city_to_node[city1], self.city_to_node[city2]
        if start == goal:
            return 0

        adjacency: Dict[str, List[Tuple[str, int]]] = {}
        for route in self.routes:
            node_a, node_b = self.endpoints(route)
            adjacency.setdefault(node_a, []).append((node_b, route.length))
            adjacency.setdefault(node_b, []).append((node_a, route.length))

        best: Dict[str, int] = {start: 0}
        frontier: List[Tuple[int, str]] = [(0, start)]
        while frontier:
            cost, node = heapq.heappop(frontier)
            if node == goal:
                return cost
            if cost > best.get(node, cost):
                continue
            for neighbor, length in adjacency.get(node, []):
                next_cost = cost + length
                if next_cost < best.get(neighbor, next_cost + 1):
                    best[neighbor] = next_cost
                    heapq.heappush(frontier, (next_cost, neighbor))
        return None


def contract_map(
    routes: List[Route],
    player_count: int,
    claimed_by: 'Dict[str, str | None]',
    player_id: str,
) -> CulledMap:
    """Build a player's culled map from an explicit claim assignment.

    Pure function of its inputs: `claimed_by` maps route_id -> claiming
    player (missing/None = unclaimed), so callers can pass live claims
    (MapGraph.culled_map_for) or claims reconstructed from a stored snapshot
    (harness playback, display API) and get the identical view.
    """
    components = _UnionFind()
    cities: Set[str] = set()
    for route in routes:
        cities.update((route.city1, route.city2))
        if claimed_by.get(route.route_id) == player_id:
            components.union(route.city1, route.city2)

    members_by_root: Dict[str, List[str]] = {}
    for city in sorted(cities):
        members_by_root.setdefault(components.find(city), []).append(city)
    node_by_root = {root: "+".join(members) for root, members in members_by_root.items()}
    city_to_node = {city: node_by_root[components.find(city)] for city in cities}

    siblings_by_key: Dict[tuple, List[Route]] = {}
    for route in routes:
        siblings_by_key.setdefault(route.sibling_group_key(), []).append(route)

    def claim_of(route: Route) -> 'str | None':
        return claimed_by.get(route.route_id)

    surviving: List[Route] = []
    for route in routes:
        siblings = [s for s in siblings_by_key[route.sibling_group_key()] if s is not route]
        if not _route_claimable_by(route, siblings, claim_of, player_id, player_count):
            continue
        if city_to_node[route.city1] == city_to_node[route.city2]:
            continue  # self-loop inside the player's own network: no connectivity gained
        surviving.append(route)

    return CulledMap(
        player_id=player_id,
        city_to_node=city_to_node,
        nodes=sorted(node_by_root.values()),
        routes=surviving,
    )


class MapGraph:
    def __init__(self, player_count: int = 4, map_name: Optional[str] = None):
        """Load the map and prepare tracking of routes and paths."""
        self.player_count = player_count
        self.map_name = map_name or DEFAULT_MAP_NAME
        self.longest_path_holder: str = ""
        self.longest_paths: Dict[str,int] = {}
        self.routes: List[Route] = []
        self._load_routes_from_csv(resolve_map_path(map_name))

        #paths hold dicts that associate player_ids with a list comprised of tuples containing (sets of connected cities, longest path length)
        self.paths: 'Dict[str,List[tuple[set[str],int]]]' = {}
        self.longest_paths: Dict[str,int]
        self.longest_path_holder: str

        self._adj: Dict[str, List[Route]] = {}
        self._build_adjacency()

        # One union-find per player, updated on every claim: which cities has
        # this player already joined into one network? Feeds are_connected()
        # and (via culled_map_for) ticket completion and bot reachability.
        self._claim_components: Dict[str, _UnionFind] = {}


    def _load_routes_from_csv(self, csv_path: str | Path):
        """Load all map routes from a CSV file."""
        route_group_counts: Counter[tuple[tuple[str, str], int]] = Counter()
        with open(csv_path, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                city1 = row["city1"]
                city2 = row["city2"]
                length = int(row["Distance"])
                color = row["Color"]
                route_key = (tuple(sorted((city1, city2))), length)
                route_group_counts[route_key] += 1
                route_index = route_group_counts[route_key]
                route_id = f"{city1.replace(' ', '_')}-{city2.replace(' ', '_')}-{route_index}"

                route = Route(city1, city2, length, color, route_id)
                self.routes.append(route)

    def _build_adjacency(self, player_id=None) -> Dict[str, List[Route]]:
        """Generate adjacency lists used for path finding."""
        if player_id is not None:
            player_adj: Dict[str, List[Route]] = {}
            for route in self.routes:
                if route.claimed_by == player_id:
                    player_adj.setdefault(route.city1, []).append(route)
                    player_adj.setdefault(route.city2, []).append(route)
            return player_adj
        for route in self.routes:
            self._adj.setdefault(route.city1, []).append(route)
            self._adj.setdefault(route.city2, []).append(route)
        return self._adj

    def get_sibling_routes(self, route: Route) -> List[Route]:
        return [candidate for candidate in self.routes if candidate is not route and candidate.sibling_group_key() == route.sibling_group_key()]

    def is_route_claimable(self, route: Route, player_id: Optional[str] = None) -> bool:
        if route not in self.routes:
            return False
        return _route_claimable_by(
            route,
            self.get_sibling_routes(route),
            lambda candidate: candidate.claimed_by,
            player_id,
            self.player_count,
        )

    def claim_route(self, route: Route, player_id: str):
        """Mark a route as claimed by the given player."""
        if not self.is_route_claimable(route, player_id):
            raise ValueError(f"Route {route.route_id} is not claimable by {player_id}.")
        route.claimed_by = player_id
        self._claim_components.setdefault(player_id, _UnionFind()).union(route.city1, route.city2)

    def are_connected(self, player_id: str, city1: str, city2: str) -> bool:
        """True if the player's claimed routes already join the two cities."""
        components = self._claim_components.get(player_id)
        return components is not None and components.connected(city1, city2)

    def culled_map_for(self, player_id: str) -> CulledMap:
        """The player's contracted view of the current board (see contract_map)."""
        claimed_by = {route.route_id: route.claimed_by for route in self.routes if route.claimed_by}
        return contract_map(self.routes, self.player_count, claimed_by, player_id)

    def cities(self) -> Set[str]:
        """Return a set of every city on the map."""
        return set(self._adj.keys())




    def get_available_routes(self, player_id: Optional[str] = None) -> List[Route]:
        """Return all routes that have not been claimed."""
        return [route for route in self.routes if self.is_route_claimable(route, player_id)]

    def get_claimed_routes(self, player_id: str) -> List[Route]:
        """Return all routes claimed by the specified player."""
        return [route for route in self.routes if route.claimed_by == player_id]

    def update_longest_path(self, player_id: str, new_route: Route):
        """Update tracking for longest continuous path after a claim."""
        # 1. Gather the endpoints of the newly claimed route
        starting_points: Set[str] = {new_route.city1, new_route.city2}

        # 2. Merge existing components that touch these cities
        if player_id not in self.paths.keys():
            self.paths[player_id] = []
        for (cities, length) in self.paths[player_id]:
            if new_route.city1 in cities or new_route.city2 in cities:
                starting_points.update(cities)
                self.paths[player_id].remove((cities,length))


        # 3. Recompute this component's longest path length
        new_length = self.get_longest_path(player_id, starting_points)

        # 4. Update player's overall longest
        other_best = max((l for (_, l) in self.paths[player_id]), default=0)
        self.longest_paths[player_id] = max(new_length, other_best)

        # 5. Store the merged component
        self.paths[player_id].append((starting_points, new_length))

        # 6. Possibly update the global longest-path holder
        holder_len = self.longest_paths.get(self.longest_path_holder, 0)
        if self.longest_paths[player_id] > holder_len:
            self.longest_path_holder = player_id

    def get_longest_path(self, player_id: str, cities: Set[str]) -> int:
        """Return the longest path length for a connected set of cities."""
        # Build adjacency for this player
        adj = self._build_adjacency(player_id)
        max_length = 0
        for city in cities:
            length = self.dfs(city, set(), 0,player_id)
            max_length = max(max_length, length)
        return max_length

    def dfs(self, current_city: str, visited: Set[Route], current_best: int, player_id: str) -> int:
        """Depth-first search used by longest path calculations."""
        # Explore all unvisited routes from current_city
        adj = self._build_adjacency(player_id)
        best = 0
        children = [r for r in adj.get(current_city, []) if r not in visited]
        if len(children) > 0:
            for r in children:
                nxt = r.other_city(current_city)
                new_length = self.dfs(nxt, visited | {r},current_best + r.length, player_id)
                best = max(best, new_length)
        else:
            group = self.is_city_in_groups(current_city, player_id)
            set_to_add = set()
            for r in visited:
                set_to_add.update(r.get_cities())
            if group:
                group.update(set_to_add)
            else:
                self.paths[player_id].append((set_to_add,best))
        return best

    

    def is_city_in_groups(self,city: str,player_id:str) -> 'set[str] | None':
        """Helper for tracking connected components on the map."""
        for (g,l) in self.paths[player_id]:
            if city in g:
                return g
        return None
