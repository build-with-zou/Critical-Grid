"""Grid-coordinate value object.

`Position` is the smallest spatial abstraction shared by map, building, and
enemy path calculations. It sits at the foundation of the domain model and
does not depend on other project modules. `GridMap`, `Building`, `Enemy`,
`PowerGrid`, and `TextRenderer` all use it; coordinates are stored in sets and
dictionaries, so immutability and ordering are intentional.

The origin is the top-left corner. `x` increases to the right and `y`
increases downward. Integer positions identify small cells; WorldPosition
represents continuous locations. Four-way occupancy adjacency is independent
of the replaceable combat-distance policy in world_distance().
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite


# Migration scale: one former demo tile spans three new world units.
# Runtime geometry uses small-cell units directly; no conversion is needed
# between a world distance and the corresponding number of small cells.
LEGACY_TILE_SIZE = 3
DISTANCE_METRIC = "manhattan"  # Update alongside the combat policy below.


@dataclass(frozen=True, order=True)
class Position:
    """Immutable, sortable two-dimensional integer grid coordinate."""

    x: int  # Column coordinate; positive points right.
    y: int  # Row coordinate; positive points down.

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (self.x, self.y)
        ):
            raise ValueError("Grid coordinates must be integers.")

    @property
    def center(self) -> "WorldPosition":
        """Return the cell center; integer world coordinates mark cell edges."""
        return WorldPosition(self.x + 0.5, self.y + 0.5)

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


@dataclass(frozen=True)
class WorldPosition:
    """Continuous position in world units, with one small cell per unit."""

    x: float
    y: float

    def __post_init__(self) -> None:
        for value in (self.x, self.y):
            try:
                valid = (
                    not isinstance(value, bool)
                    and isinstance(value, (int, float))
                    and isfinite(value)
                )
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError("World coordinates must be finite numbers.")

    @property
    def cell(self) -> Position:
        """Return the containing small cell, including for negative positions."""
        return Position(floor(self.x), floor(self.y))


def world_distance(first: WorldPosition, second: WorldPosition) -> float:
    """Measure combat distance using the current Manhattan policy.

    Combat rules call this boundary instead of embedding a distance formula.
    A future Euclidean/range policy can replace it without changing grid
    occupancy, four-way power adjacency, or physical route lengths.
    """
    return abs(first.x - second.x) + abs(first.y - second.y)


@dataclass(frozen=True)
class Footprint:
    """Immutable rectangular building size, measured in whole small cells."""

    width: int
    height: int

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (self.width, self.height)
        ):
            raise ValueError("Footprint dimensions must be positive integers.")

    def cells(self, anchor: Position) -> tuple[Position, ...]:
        """Enumerate occupied cells from an inclusive top-left anchor."""
        return tuple(
            Position(x, y)
            for y in range(anchor.y, anchor.y + self.height)
            for x in range(anchor.x, anchor.x + self.width)
        )

    def contains(self, anchor: Position, position: Position) -> bool:
        """Test occupancy without allocating the full cell collection."""
        return (
            anchor.x <= position.x < anchor.x + self.width
            and anchor.y <= position.y < anchor.y + self.height
        )

    def center(self, anchor: Position) -> WorldPosition:
        """Return the geometric center, also supporting even dimensions."""
        return WorldPosition(anchor.x + self.width / 2, anchor.y + self.height / 2)

