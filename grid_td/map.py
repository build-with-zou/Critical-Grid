"""Fixed grid map and static terrain rules.

This module sits in the domain foundation layer. It stores map dimensions, the
fixed enemy route, the core position, mine sites, high-ground cells, and
blocked terrain, then provides queries that do not involve runtime entities.
`GameState` uses these rules for build validation, `Enemy` uses `route` to map
path progress, and `TextRenderer` uses terrain queries to produce the
character map.

`GridMap` is a frozen data object, so these methods do not change the layout
during a run. Note that `is_buildable()` only checks bounds, route cells, and
static blocked terrain. Occupancy, mine-site type, gold, and dynamic pathing
constraints are validated by `GameState.build()`.
"""

from __future__ import annotations

from dataclasses import dataclass

from grid_td.position import Position


@dataclass(frozen=True)
class GridMap:
    """Describe one fixed map and its static terrain markers.

    `route` is ordered by enemy travel direction. In the current demo route,
    the final cell sits before the core, and enemies move by route index
    rather than by independent coordinates.
    """

    width: int  # Number of columns; valid x values are [0, width).
    height: int  # Number of rows; valid y values are [0, height).
    route: tuple[Position, ...]  # Route cells ordered from entrance to core.
    core_position: Position  # Core cell; build rules forbid occupying it.
    mine_positions: frozenset[Position]  # Mine-only build cells.
    high_ground_positions: frozenset[Position]  # Cells that grant tower range.
    illegal_ground_positions: frozenset[Position]  # Static blocked cells.

    def in_bounds(self, position: Position) -> bool:
        """Return whether a coordinate lies inside the map rectangle."""
        return 0 <= position.x < self.width and 0 <= position.y < self.height

    def is_route(self, position: Position) -> bool:
        """Return whether a coordinate belongs to the fixed enemy route."""
        return position in self.route

    def is_mine_site(self, position: Position) -> bool:
        """Return whether a coordinate is a mine-only site."""
        return position in self.mine_positions

    def is_high_ground(self, position: Position) -> bool:
        """Return whether a coordinate grants high-ground bonuses."""
        return position in self.high_ground_positions

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
        if position == self.core_position:
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
        An immutable 12-column, 7-row map with a route that runs horizontally
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

    return GridMap(
        width=12,
        height=7,
        route=route,
        core_position=Position(10, 1),
        mine_positions=frozenset(
            {
                Position(2, 1),
                Position(8, 5),
            }
        ),
        high_ground_positions=frozenset(
            {
                Position(4, 2),
                Position(7, 2),
            }
        ),
        illegal_ground_positions=frozenset(
            {
                Position(0, 0),
                Position(1, 0),
                Position(5, 0),
                Position(6, 0),
                Position(11, 2),
                Position(11, 3),
                Position(4, 6),
                Position(5, 6),
            }
        ),
    )

