"""Enemy entities and enemy templates.

This module sits in the combat domain layer. It stores enemy health, speed,
route progress, slow state, and reward, and provides a factory that creates
independent instances from string templates. `WaveRunner` calls
`create_enemy()` to spawn enemies, `GameState` advances them, selects them as
targets, applies damage, and settles rewards, and `TextRenderer` only reads
their current positions.

Enemies in the current prototype only move along `GridMap.route`. They do not
actively attack buildings or change routes. `path_progress` is measured in
route-index intervals, not pixels or absolute coordinates; future dynamic
pathfinding needs to redefine that field and its compatibility with existing
tests or saves.
"""

from __future__ import annotations

from dataclasses import dataclass

from grid_td.position import Position


@dataclass
class Enemy:
    """Enemy state that towers can attack while it moves along a fixed route."""

    name: str  # Display name or debug identifier.
    max_hp: float  # Maximum health.
    speed: float  # Route-index units advanced per logical second when unslowed.
    damage_to_core: int  # Damage dealt to the core on reaching route end.
    reward: int  # Gold immediately awarded to GameState when defeated.
    path_progress: float = 0.0  # Continuous progress from the route start.
    hp: float = 0.0  # Current health; non-positive values are reset to full.
    slow_seconds_remaining: float = 0.0  # Logical seconds of slow remaining.

    def __post_init__(self) -> None:
        """Ensure template-created enemies start at full health by default."""
        if self.hp <= 0:
            self.hp = self.max_hp

    @property
    def is_alive(self) -> bool:
        """Return whether the enemy can still be attacked or moved."""
        return self.hp > 0

    @property
    def is_slowed(self) -> bool:
        """Return whether the enemy is still inside a slow-effect window."""
        return self.slow_seconds_remaining > 0

    def current_speed(self) -> float:
        """Return current movement speed, using a fixed 55% multiplier when slowed."""
        return self.speed * (0.55 if self.is_slowed else 1.0)

    def take_damage(self, amount: float) -> None:
        """Apply damage and clamp health at zero to avoid negative values."""
        self.hp = max(0.0, self.hp - amount)

    def apply_slow(self, seconds: float) -> None:
        """Apply slow, keeping the longer remaining duration on repeated hits."""
        self.slow_seconds_remaining = max(self.slow_seconds_remaining, seconds)

    def advance(self, seconds: float) -> None:
        """Advance along the route at current speed and tick down slow time.

        This method does not remove the enemy or clamp progress to route end.
        The state layer calls `has_reached_core()` afterward to decide whether
        escape should be settled.
        """
        self.path_progress += self.current_speed() * seconds
        self.slow_seconds_remaining = max(0.0, self.slow_seconds_remaining - seconds)

    def position_on_route(self, route: tuple[Position, ...]) -> Position:
        """Map continuous route progress to the current grid cell.

        Progress is floored and clamped to the last route cell, so multiple
        enemies may overlap in the same rendered cell. The caller must provide
        a non-empty `route`.
        """
        route_index = min(int(self.path_progress), len(route) - 1)
        return route[route_index]

    def has_reached_core(self, route: tuple[Position, ...]) -> bool:
        """Return whether the enemy has reached the route-end core-adjacent cell."""
        return self.path_progress >= len(route) - 1


def create_enemy(kind: str) -> Enemy:
    """Create an independent enemy instance from a template key.

    Args:
        kind: Supports `basic`, `fast`, `armored`, and `saboteur`.

    Returns:
        An `Enemy` with independent health and slow timers. Template objects
        are not modified by runtime state.

    Raises:
        ValueError: Unknown enemy type.
    """
    templates = {
        "basic": Enemy("Basic", max_hp=10, speed=0.75, damage_to_core=1, reward=4),
        "fast": Enemy("Fast", max_hp=7, speed=1.25, damage_to_core=1, reward=5),
        "armored": Enemy("Armored", max_hp=24, speed=0.45, damage_to_core=2, reward=8),
        "saboteur": Enemy("Saboteur", max_hp=14, speed=0.85, damage_to_core=2, reward=7),
    }

    try:
        template = templates[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown enemy kind: {kind}") from exc

    return Enemy(
        name=template.name,
        max_hp=template.max_hp,
        speed=template.speed,
        damage_to_core=template.damage_to_core,
        reward=template.reward,
    )

