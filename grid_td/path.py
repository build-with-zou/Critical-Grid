"""Distance-based movement along an immutable orthogonal centerline."""

from bisect import bisect_right
from dataclasses import dataclass, field
from math import isfinite

from grid_td.position import WorldPosition


@dataclass(frozen=True)
class RoutePath:
    """A fixed centerline independent of road width and waypoint spacing.

    Movement is measured in world units, never waypoint indices. Orthogonal
    segment lengths are physical lengths, independent of the combat metric.
    Collinear waypoints may be inserted without changing travel time.
    """

    points: tuple[WorldPosition, ...]
    cumulative_lengths: tuple[float, ...] = field(init=False)

    def __post_init__(self) -> None:
        # Capture callers' input so later list edits cannot invalidate cached
        # lengths or mutate a path already owned by a frozen map.
        object.__setattr__(self, "points", tuple(self.points))
        if not self.points or any(not isinstance(point, WorldPosition) for point in self.points):
            raise ValueError("A route must contain at least one point.")
        lengths = [0.0]
        for start, end in zip(self.points, self.points[1:]):
            dx, dy = abs(end.x - start.x), abs(end.y - start.y)
            if (dx and dy) or not (dx or dy):
                raise ValueError("Route segments must be nonzero and orthogonal.")
            length = lengths[-1] + dx + dy
            if not isfinite(length):
                raise ValueError("Route length must be finite.")
            lengths.append(length)
        object.__setattr__(self, "cumulative_lengths", tuple(lengths))

    @property
    def length(self) -> float:
        """Return the total physical travel distance in small-cell units."""
        return self.cumulative_lengths[-1]

    def position_at(self, distance: float) -> WorldPosition:
        """Clamp route progress and interpolate within its current segment.

        Sampling uses cumulative distances so a three-unit segment takes
        three times as long to traverse as a one-unit segment at equal speed.
        The last centerline point remains the prototype's core-arrival point.
        """
        if not isfinite(distance):
            raise ValueError("Route progress must be finite.")
        if distance <= 0:
            return self.points[0]
        if distance >= self.length:
            return self.points[-1]
        index = bisect_right(self.cumulative_lengths, distance) - 1
        start, end = self.points[index:index + 2]
        fraction = ((distance - self.cumulative_lengths[index]) /
                    (self.cumulative_lengths[index + 1] - self.cumulative_lengths[index]))
        return WorldPosition(start.x + (end.x - start.x) * fraction,
                             start.y + (end.y - start.y) * fraction)
