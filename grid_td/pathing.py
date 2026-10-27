"""Grid pathfinding with optional breachable building nodes.

The first prototype supports open-ground movement: cells marked walkable by
`GridMap.is_walkable()` are traversable unless occupied by a living building.
Buildings can be included in the search as extra nodes. Entering a building
node costs the time needed to destroy it, which lets the same search compare
a normal detour against breaking through a wall.
"""

from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from math import isfinite

from grid_td.buildings import Building, Core
from grid_td.map import GridMap
from grid_td.path import RoutePath
from grid_td.position import Position, WorldPosition


@dataclass(frozen=True)
class PathPlan:
    """A movement plan to the core or to the first breach target."""

    route: RoutePath
    time_seconds: float  # Selected total estimate; includes planned breaches.
    breach_target_id: int | None
    breach_target_position: Position | None
    used_breach: bool
    normal_time: float | None
    breach_time: float | None


@dataclass(frozen=True)
class _SearchResult:
    cost: float
    nodes: tuple[tuple[int, int, int], ...]
    uses_building: bool


def _cell_key(position: Position) -> tuple[int, int, int]:
    return (0, position.x, position.y)


def _building_key(building_id: int) -> tuple[int, int, int]:
    return (1, building_id, 0)


def _key_position(key: tuple[int, int, int]) -> Position:
    return Position(key[1], key[2])


def _validate_positive_number(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite positive number.")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(f"{label} must be a finite positive number.") from None
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a finite positive number.")
    return number


def _compress_route(cells: list[Position]) -> RoutePath:
    """Convert orthogonal cell steps into a compressed RoutePath."""
    if not cells:
        raise ValueError("A path must contain at least one cell.")
    points = [cell.center for cell in cells]
    if len(points) <= 2:
        return RoutePath(tuple(points))

    compressed: list[WorldPosition] = [points[0]]
    for index in range(1, len(points) - 1):
        previous, current, following = points[index - 1], points[index], points[index + 1]
        if previous.x == current.x == following.x:
            continue
        if previous.y == current.y == following.y:
            continue
        compressed.append(current)
    compressed.append(points[-1])
    return RoutePath(tuple(compressed))


def find_path(
    grid_map: GridMap,
    buildings: list[Building],
    start: Position,
    *,
    enemy_speed: float,
    breach_damage: float,
    breach_time_ratio: float = 1.5,
) -> PathPlan | None:
    """Plan a route to the core, optionally breaching buildings.

    Args:
        grid_map: Static terrain and core geometry.
        buildings: Current buildings. The core and destroyed buildings are not
            treated as blockers.
        start: Current small cell of the mover.
        enemy_speed: World units per logical second.
        breach_damage: Damage per second against a blocking building.
        breach_time_ratio: Choose a breach when the normal route takes more
            than this multiple of the breach route time.

    Returns:
        A normal plan to a core-adjacent cell, a breach plan whose route ends
        at the first building to attack, or `None` when no plan exists.

    Raises:
        ValueError: Invalid speed/damage/ratio or an unwalkable start cell.
    """
    speed = _validate_positive_number(enemy_speed, "Enemy speed")
    damage = _validate_positive_number(breach_damage, "Breach damage")
    ratio = _validate_positive_number(breach_time_ratio, "Breach time ratio")
    if not isinstance(start, Position):
        raise ValueError("Path start must be a grid Position.")

    alive_buildings = [
        building
        for building in buildings
        if not isinstance(building, Core) and not building.is_destroyed
    ]

    blocked_cells: set[Position] = set()
    building_by_cell: dict[Position, Building] = {}
    for building in alive_buildings:
        for cell in building.occupied_cells():
            blocked_cells.add(cell)
            building_by_cell[cell] = building

    walkable_cells = {
        Position(x, y)
        for y in range(grid_map.height)
        for x in range(grid_map.width)
        if grid_map.is_walkable(Position(x, y))
        and Position(x, y) not in blocked_cells
    }
    if start not in walkable_cells:
        raise ValueError("Path start must be a walkable, unoccupied cell.")

    core_cells = set(
        grid_map.core_footprint.cells(grid_map.core_position)
    )
    goal_cells = {
        neighbor
        for cell in core_cells
        for neighbor in cell.neighbors()
        if neighbor in walkable_cells
    }
    goal_buildings = {
        building.id
        for building in alive_buildings
        if any(
            neighbor in core_cells
            for cell in building.occupied_cells()
            for neighbor in cell.neighbors()
        )
    }

    building_adjacent_cells: dict[int, set[Position]] = {
        building.id: set() for building in alive_buildings
    }
    building_adjacent_buildings: dict[int, set[int]] = {
        building.id: set() for building in alive_buildings
    }
    for building in alive_buildings:
        for cell in building.occupied_cells():
            for neighbor in cell.neighbors():
                if neighbor in walkable_cells:
                    building_adjacent_cells[building.id].add(neighbor)
                other = building_by_cell.get(neighbor)
                if other is not None and other.id != building.id:
                    building_adjacent_buildings[building.id].add(other.id)

    cell_to_buildings: dict[Position, set[int]] = {}
    for building_id, cells in building_adjacent_cells.items():
        for cell in cells:
            cell_to_buildings.setdefault(cell, set()).add(building_id)

    building_breach_time = {
        building.id: building.hp / damage for building in alive_buildings
    }
    step_time = 1.0 / speed
    start_key = _cell_key(start)

    def search(allow_buildings: bool) -> _SearchResult | None:
        goals = set(goal_cells)
        if allow_buildings:
            goals.update(goal_buildings)

        distances: dict[tuple[int, int, int], float] = {start_key: 0.0}
        parents: dict[tuple[int, int, int], tuple[int, int, int]] = {}
        heap: list[tuple[float, int, tuple[int, int, int]]] = []
        sequence = count()
        heappush(heap, (0.0, next(sequence), start_key))

        goal_key: tuple[int, int, int] | None = None
        while heap:
            cost, _, node = heappop(heap)
            if cost > distances.get(node, float("inf")):
                continue

            if node[0] == 0:
                position = _key_position(node)
                if position in goals:
                    goal_key = node
                    break
                for neighbor in position.neighbors():
                    if neighbor not in walkable_cells:
                        continue
                    next_node = _cell_key(neighbor)
                    next_cost = cost + step_time
                    if next_cost < distances.get(next_node, float("inf")):
                        distances[next_node] = next_cost
                        parents[next_node] = node
                        heappush(heap, (next_cost, next(sequence), next_node))
                if allow_buildings:
                    for building_id in cell_to_buildings.get(position, ()):
                        next_node = _building_key(building_id)
                        next_cost = cost + building_breach_time[building_id]
                        if next_cost < distances.get(next_node, float("inf")):
                            distances[next_node] = next_cost
                            parents[next_node] = node
                            heappush(heap, (next_cost, next(sequence), next_node))
            else:
                building_id = node[1]
                if building_id in goal_buildings:
                    goal_key = node
                    break
                for cell in building_adjacent_cells.get(building_id, ()):
                    next_node = _cell_key(cell)
                    next_cost = cost + step_time
                    if next_cost < distances.get(next_node, float("inf")):
                        distances[next_node] = next_cost
                        parents[next_node] = node
                        heappush(heap, (next_cost, next(sequence), next_node))
                if allow_buildings:
                    for other_id in building_adjacent_buildings.get(building_id, ()):
                        next_node = _building_key(other_id)
                        next_cost = cost + building_breach_time[other_id]
                        if next_cost < distances.get(next_node, float("inf")):
                            distances[next_node] = next_cost
                            parents[next_node] = node
                            heappush(heap, (next_cost, next(sequence), next_node))

        if goal_key is None:
            return None

        nodes: list[tuple[int, int, int]] = []
        current = goal_key
        while True:
            nodes.append(current)
            if current == start_key:
                break
            current = parents[current]
        nodes.reverse()
        return _SearchResult(
            cost=distances[goal_key],
            nodes=tuple(nodes),
            uses_building=any(node[0] == 1 for node in nodes),
        )

    normal = search(False)
    breach = search(True)

    if normal is not None and (
        breach is None or not breach.uses_building or normal.cost <= breach.cost * ratio
    ):
        normal_cells = [
            _key_position(node) for node in normal.nodes if node[0] == 0
        ]
        return PathPlan(
            route=_compress_route(normal_cells),
            time_seconds=normal.cost,
            breach_target_id=None,
            breach_target_position=None,
            used_breach=False,
            normal_time=normal.cost,
            breach_time=breach.cost if breach is not None else None,
        )

    if breach is None or not breach.uses_building:
        return None

    first_building_index = next(
        index for index, node in enumerate(breach.nodes) if node[0] == 1
    )
    first_building_node = breach.nodes[first_building_index]
    building_id = first_building_node[1]
    building = next(b for b in alive_buildings if b.id == building_id)
    approach_cells = [
        _key_position(node)
        for node in breach.nodes[:first_building_index]
        if node[0] == 0
    ]
    # The path should contain at least the starting cell. Keep a single-point
    # route when the mover is already adjacent to the breach target.
    if not approach_cells:
        approach_cells = [start]
    return PathPlan(
        route=_compress_route(approach_cells),
        time_seconds=breach.cost,
        breach_target_id=building_id,
        breach_target_position=building.position,
        used_breach=True,
        normal_time=normal.cost if normal is not None else None,
        breach_time=breach.cost,
    )
