from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Position:
    x: int
    y: int

    def neighbors(self) -> tuple["Position", ...]:
        return (
            Position(self.x + 1, self.y),
            Position(self.x - 1, self.y),
            Position(self.x, self.y + 1),
            Position(self.x, self.y - 1),
        )

    def manhattan_distance(self, other: "Position") -> int:
        return abs(self.x - other.x) + abs(self.y - other.y)

