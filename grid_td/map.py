"""Fixed grid map and static terrain rules.

This module sits in the domain foundation layer. It stores map dimensions, the
fixed enemy route, the core position, mine sites, high-ground cells, and
blocked terrain, then provides queries that do not involve runtime entities.
`GameState` uses these rules for build validation. Enemies sample the cached
physical path, while snapshots expose both terrain and continuous positions
for presentation layers.

`GridMap` is a frozen data object, so these methods do not change the layout
during a run. `is_walkable()` and `is_buildable_terrain()` expose the
pathfinding-ready terrain capabilities, including optional walk-only and
build-only cells. The older `is_buildable()` remains the current prototype
build rule; occupancy, mine-site type, gold, and dynamic pathing constraints
are validated by `GameState.build()`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property

from grid_td.path import RoutePath
from grid_td.position import Footprint, LEGACY_TILE_SIZE, Position


@dataclass(frozen=True)
class GridMap:
    """Describe one fixed map and its static terrain markers.

    `route` stores ordered centerline cells, which need not be adjacent.
    `road_cells` independently stores all cells of the wider road surface.
    The final centerline point remains the core-adjacent arrival point.
    """

    width: int  # Number of columns; valid x values are [0, width).
    height: int  # Number of rows; valid y values are [0, height).
    route: tuple[Position, ...]  # Route cells ordered from entrance to core.
    core_position: Position  # Top-left anchor of the reserved core rectangle.
    mine_positions: frozenset[Position]  # Mine-only build cells.
    high_ground_positions: frozenset[Position]  # Cells that grant tower range.
    illegal_ground_positions: frozenset[Position]  # Static blocked cells.
    road_cells: frozenset[Position] | None = None
    core_footprint: Footprint = Footprint(3, 3)
    walk_only_positions: frozenset[Position] = frozenset()
    build_only_positions: frozenset[Position] = frozenset()

    def __post_init__(self) -> None:
        """Reject geometry that would place runtime entities outside the map."""
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (self.width, self.height)
        ):
            raise ValueError("Map dimensions must be positive integers.")
        if not self.route or any(not self.in_bounds(point) for point in self.route):
            raise ValueError("Route waypoints must be nonempty and inside the map.")
        if any(not self.in_bounds(cell) for cell in self.core_footprint.cells(self.core_position)):
            raise ValueError("The entire core footprint must be inside the map.")
        # Prepare geometry now so malformed segments fail at map creation,
        # rather than during the first enemy movement or snapshot.
        self.path
        if self.road_cells is not None:
            if any(not self.in_bounds(cell) for cell in self.road_cells):
                raise ValueError("Road terrain must be inside the map.")
            if not self.centerline_cells.issubset(self.road_cells):
                raise ValueError("Road terrain must cover the entire centerline.")
        if any(
            not self.in_bounds(cell)
            for cell in self.walk_only_positions | self.build_only_positions
        ):
            raise ValueError("Terrain capability cells must be inside the map.")
        if self.walk_only_positions & self.build_only_positions:
            raise ValueError("A cell cannot be walk-only and build-only.")

    @cached_property
    def path(self) -> RoutePath:
        """Prepare physical route geometry once, separate from road terrain."""
        return RoutePath(tuple(position.center for position in self.route))

    @cached_property
    def centerline_cells(self) -> frozenset[Position]:
        """Rasterize sparse waypoints to reserve the entire centerline."""
        cells = set(self.route)
        for start, end in zip(self.route, self.route[1:]):
            dx = (end.x > start.x) - (end.x < start.x)
            dy = (end.y > start.y) - (end.y < start.y)
            for offset in range(start.manhattan_distance(end) + 1):
                cells.add(Position(start.x + dx * offset, start.y + dy * offset))
        return frozenset(cells)

    @cached_property
    def route_cells(self) -> frozenset[Position]:
        """Return full road terrain, defaulting to the one-cell-wide centerline."""
        return self.road_cells if self.road_cells is not None else self.centerline_cells

    def is_core(self, position: Position) -> bool:
        """Reserve the full core footprint, not just its anchor cell."""
        return self.core_footprint.contains(self.core_position, position)

    def in_bounds(self, position: Position) -> bool:
        """Return whether a coordinate lies inside the map rectangle."""
        return 0 <= position.x < self.width and 0 <= position.y < self.height

    def is_route(self, position: Position) -> bool:
        """Return whether a coordinate belongs to the fixed enemy route."""
        return position in self.route_cells

    def is_mine_site(self, position: Position) -> bool:
        """Return whether a coordinate is a mine-only site."""
        return position in self.mine_positions

    def is_high_ground(self, position: Position) -> bool:
        """Return whether a coordinate grants high-ground bonuses."""
        return position in self.high_ground_positions

    def is_walkable(self, position: Position) -> bool:
        """Return whether static terrain permits enemy movement.

        Buildings are dynamic blockers and are not considered here. Roads,
        mine sites, high ground and ordinary ground are walkable; illegal,
        core and build-only cells are not.
        """
        if not self.in_bounds(position):
            return False
        if self.is_core(position) or self.is_illegal(position):
            return False
        return position not in self.build_only_positions

    def is_buildable_terrain(self, position: Position) -> bool:
        """Return whether static terrain permits constructing a building.

        This is the pathfinding-ready build rule: roads are buildable and
        walk-only cells are not. Mine-site and occupancy restrictions remain
        the responsibility of `GameState.build()`.
        """
        if not self.in_bounds(position):
            return False
        if self.is_core(position) or self.is_illegal(position):
            return False
        return position not in self.walk_only_positions

    def is_buildable(self, position: Position) -> bool:
        """Return whether a coordinate satisfies static build constraints.

        Returns:
            Only indicates that the coordinate is in bounds, not on the route,
            not on blocked terrain, and not the core. Occupancy and
            building-type restrictions are handled by `GameState.build()`.
        """
        if not self.in_bounds(position):
            return False
        if self.is_route(position):
            return False
        if self.is_core(position):
            return False
        if self.is_illegal(position):
            return False
        return True

    def is_illegal(self, position: Position) -> bool:
        """Return whether the position is illegal to build."""
        return position in self.illegal_ground_positions


def create_demo_map() -> GridMap:
    """Create the fixed demo map shared by the entry script and tests.

    Returns:
        An immutable 36-column, 21-row map with a route that runs horizontally
        and then turns upward, plus two mine sites and two high-ground cells.
        Changing this also changes the spatial assumptions of the demo, tests,
        and default waves, so check build coordinates and tower ranges too.
    """
    route = (
        Position(0, 4),
        Position(1, 4),
        Position(2, 4),
        Position(3, 4),
        Position(4, 4),
        Position(5, 4),
        Position(6, 4),
        Position(7, 4),
        Position(8, 4),
        Position(9, 4),
        Position(9, 3),
        Position(9, 2),
        Position(9, 1),
    )

    def expand(cells: Iterable[Position]) -> frozenset[Position]:
        """Expand terrain area while keeping the original physical layout."""
        tile = Footprint(LEGACY_TILE_SIZE, LEGACY_TILE_SIZE)
        return frozenset(
            cell
            for old in cells
            for cell in tile.cells(Position(old.x * LEGACY_TILE_SIZE, old.y * LEGACY_TILE_SIZE))
        )

    return GridMap(
        width=12 * LEGACY_TILE_SIZE,
        height=7 * LEGACY_TILE_SIZE,
        # The middle small cell of each former tile preserves the original
        # centerline. Sparse waypoints keep its length at 12 * 3 = 36 units.
        route=tuple(
            Position(p.x * LEGACY_TILE_SIZE + 1, p.y * LEGACY_TILE_SIZE + 1)
            for p in route
        ),
        road_cells=expand(route),
        core_position=Position(10 * LEGACY_TILE_SIZE, LEGACY_TILE_SIZE),
        mine_positions=expand((Position(2, 1), Position(8, 5))),
        high_ground_positions=expand((Position(4, 2), Position(7, 2))),
        illegal_ground_positions=expand(
            (
                Position(0, 0),
                Position(1, 0),
                Position(5, 0),
                Position(6, 0),
                Position(11, 2),
                Position(11, 3),
                Position(4, 6),
                Position(5, 6),
            )
        ),
    )

