"""Grid-coordinate value object.

`Position` is the smallest spatial abstraction shared by map, building, and
enemy path calculations. It sits at the foundation of the domain model and
does not depend on other project modules. `GridMap`, `Building`, `Enemy`,
`PowerGrid`, and `TextRenderer` all use it; coordinates are stored in sets and
dictionaries, so immutability and ordering are intentional.

The origin is the top-left corner. `x` increases to the right and `y`
increases downward. The current project uses four-way adjacency and has no
diagonal movement or weighted distance; changing neighbor order or distance
semantics affects power connectivity, tower range, and rendering.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Position:
    """Immutable, sortable two-dimensional integer grid coordinate."""

    x: int  # Column coordinate; positive points right.
    y: int  # Row coordinate; positive points down.

    def neighbors(self) -> tuple["Position", ...]:
        """Return the four orthogonal neighbors in right, left, down, up order.

        Returns:
            A tuple of `Position` values excluding `self`. Neighbors are
            returned even when they are outside the map; `GridMap` or the
            caller is responsible for bounds checks.
        """
        return (
            Position(self.x + 1, self.y),
            Position(self.x - 1, self.y),
            Position(self.x, self.y + 1),
            Position(self.x, self.y - 1),
        )

    def manhattan_distance(self, other: "Position") -> int:
        """Compute grid distance for movement rules without diagonals."""
        return abs(self.x - other.x) + abs(self.y - other.y)

