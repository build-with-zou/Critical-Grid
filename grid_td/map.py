from __future__ import annotations

from dataclasses import dataclass

from grid_td.position import Position


@dataclass(frozen=True)
class GridMap:
    width: int
    height: int
    route: tuple[Position, ...]
    core_position: Position
    mine_positions: frozenset[Position]
    high_ground_positions: frozenset[Position]

    def in_bounds(self, position: Position) -> bool:
        return 0 <= position.x < self.width and 0 <= position.y < self.height

    def is_route(self, position: Position) -> bool:
        return position in self.route

    def is_mine_site(self, position: Position) -> bool:
        return position in self.mine_positions

    def is_high_ground(self, position: Position) -> bool:
        return position in self.high_ground_positions

    def is_buildable(self, position: Position) -> bool:
        if not self.in_bounds(position):
            return False
        if self.is_route(position):
            return False
        if position == self.core_position:
            return False
        return True


def create_demo_map() -> GridMap:
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
    )

