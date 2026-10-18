"""Enemy entities and enemy templates.

This module sits in the combat domain layer. It stores enemy health, speed,
route progress, slow state, and reward, and provides a factory that creates
independent instances from string templates. `WaveRunner` calls
`create_enemy()` to spawn enemies, `GameState` advances them, selects them as
targets, applies damage, and settles rewards, and `TextRenderer` only reads
their current positions.

Enemies move along `GridMap.route`. Saboteurs can also attack power nodes when
they enter their attack range; they do not yet change routes or attack other
building types. `path_progress` is physical distance along the centerline, in
small-cell world units, not waypoint indices.
"""

from __future__ import annotations

from dataclasses import dataclass

from grid_td.path import RoutePath
from grid_td.position import LEGACY_TILE_SIZE, Position, WorldPosition


@dataclass
class Enemy:
    """Enemy state that towers can attack while it moves along a fixed route."""

    name: str  # Display name or debug identifier.
    max_hp: float  # Maximum health.
    speed: float  # World units per logical second when unslowed.
    damage_to_core: int  # Damage dealt to the core on reaching route end.
    reward: int  # Gold immediately awarded to GameState when defeated.
    path_progress: float = 0.0  # Continuous progress from the route start.
    hp: float = 0.0  # Current health; non-positive values are reset to full.
    slow_seconds_remaining: float = 0.0  # Logical seconds of slow remaining.
    attack_range: float = 0.0  # World-unit range for building attacks.
    attack_damage: int = 0  # Damage per building attack.
    attack_cooldown_seconds: float = 1.0  # Interval between building attacks.
    attack_cooldown_remaining: float = 0.0  # Time until the next building attack.

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

    @property
    def can_attack_buildings(self) -> bool:
        """Return whether this enemy has a ready building attack."""
        return (
            self.attack_damage > 0
            and self.attack_range > 0
            and self.attack_cooldown_remaining <= 0
        )

    def tick_attack_cooldown(self, seconds: float) -> None:
        """Advance the building-attack cooldown without going below zero."""
        self.attack_cooldown_remaining = max(
            0.0, self.attack_cooldown_remaining - seconds
        )

    def reset_attack_cooldown(self) -> None:
        """Start the next building-attack interval after a successful attack."""
        self.attack_cooldown_remaining = self.attack_cooldown_seconds

    def advance(self, seconds: float) -> None:
        """Advance along the route at current speed and tick down slow time.

        This method does not remove the enemy or clamp progress to route end.
        The state layer calls `has_reached_core()` afterward to decide whether
        escape should be settled.
        """
        self.path_progress += self.current_speed() * seconds
        self.slow_seconds_remaining = max(0.0, self.slow_seconds_remaining - seconds)

    def world_position_on_route(self, path: RoutePath) -> WorldPosition:
        """Sample continuous position using traveled distance, not a route index."""
        return path.position_at(self.path_progress)

    def position_on_route(self, path: RoutePath) -> Position:
        """Return the small cell containing the enemy's continuous position."""
        return self.world_position_on_route(path).cell

    def has_reached_core(self, path: RoutePath) -> bool:
        """Preserve arrival at the final centerline point adjacent to the core."""
        return self.path_progress >= path.length


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
        "basic": Enemy("Basic", max_hp=10, speed=0.75 * LEGACY_TILE_SIZE, damage_to_core=1, reward=4),
        "fast": Enemy("Fast", max_hp=7, speed=1.25 * LEGACY_TILE_SIZE, damage_to_core=1, reward=5),
        "armored": Enemy("Armored", max_hp=24, speed=0.45 * LEGACY_TILE_SIZE, damage_to_core=2, reward=8),
        "saboteur": Enemy(
            "Saboteur",
            max_hp=14,
            speed=0.85 * LEGACY_TILE_SIZE,
            damage_to_core=2,
            reward=7,
            attack_range=6.0,
            attack_damage=1,
            attack_cooldown_seconds=1.0,
        ),
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
        attack_range=template.attack_range,
        attack_damage=template.attack_damage,
        attack_cooldown_seconds=template.attack_cooldown_seconds,
    )

