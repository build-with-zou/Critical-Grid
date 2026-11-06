"""Wave configuration and enemy-spawn progress.

This module describes each wave as independent `SpawnGroup` values, then lets
`WaveRunner` create enemy instances according to logical time. It belongs to
the configuration/scheduling layer: `GameState` holds the current runner and
pulls new enemies on each `step()`. This module does not add enemies to the
game list, move them, or decide whether the player has won or lost.

`WaveRunner.is_complete` only means all configured enemies have spawned. It
does not mean the board is empty. The full wave-end condition is checked by
`GameState.waiting_for_next_wave`, which combines spawn progress with the
active enemy list.
"""

from __future__ import annotations

from dataclasses import dataclass

from grid_td.enemies import Enemy, create_enemy


THREAT_LEVELS: frozenset[str] = frozenset({"low", "medium", "high"})
"""Allowed authored threat tiers; shared with level validation and intel."""


@dataclass(frozen=True)
class SpawnGroup:
    """Timed spawn configuration for one enemy type."""

    enemy_kind: str  # Template key passed to create_enemy().
    count: int  # Maximum number of enemies spawned by this group.
    interval_seconds: float  # Logical interval between enemies in this group.
    start_delay_seconds: float = 0.0  # First-spawn delay from wave start.
    entrance: int = 0  # Zero-based entry in GridMap.spawn_entrances.


@dataclass(frozen=True)
class Wave:
    """Static configuration and player-facing briefing for one wave."""

    name: str  # Wave name shown in the status line.
    briefing: str  # Coarse description shown by free and detailed intel.
    groups: tuple[SpawnGroup, ...]  # Spawn groups advanced in parallel.
    threat: str | None = None  # Optional low/medium/high override for intel.
    reward: int = 0  # Gold paid at settlement, before interest and repairs.

    def __post_init__(self) -> None:
        """Reject authored threat and reward values outside the shared rules."""
        if self.threat is not None:
            if not isinstance(self.threat, str) or self.threat not in THREAT_LEVELS:
                raise ValueError(
                    "Wave threat must be one of: low, medium, high."
                )
        if (
            isinstance(self.reward, bool)
            or not isinstance(self.reward, int)
            or self.reward < 0
        ):
            raise ValueError("Wave reward must be a non-negative integer.")


class WaveRunner:
    """Maintain one wave's logical clock and spawned counts."""

    def __init__(self, wave: Wave) -> None:
        """Start the given wave from zero without sharing runner state."""
        self.wave = wave
        self.elapsed_seconds = 0.0
        self.spawned_counts = [0 for _ in wave.groups]

    @property
    def is_complete(self) -> bool:
        """Return whether every spawn group has reached its configured count."""
        return all(
            spawned >= group.count
            for spawned, group in zip(self.spawned_counts, self.wave.groups)
        )

    def step(self, seconds: float) -> list[Enemy]:
        """Advance the wave clock and return enemies due in this time step.

        If one step crosses multiple spawn times, the internal `while` catches
        up by spawning multiple enemies in the same call. Each group uses its
        own delay and interval, and cross-group return order follows
        `wave.groups`.
        """
        self.elapsed_seconds += seconds
        spawned_enemies: list[Enemy] = []

        for index, group in enumerate(self.wave.groups):
            spawned = self.spawned_counts[index]

            while spawned < group.count:
                spawn_time = group.start_delay_seconds + spawned * group.interval_seconds
                if self.elapsed_seconds < spawn_time:
                    break

                enemy = create_enemy(group.enemy_kind)
                enemy.entrance_index = group.entrance
                spawned_enemies.append(enemy)
                spawned += 1

            self.spawned_counts[index] = spawned

        return spawned_enemies


def create_demo_waves() -> tuple[Wave, ...]:
    """Load the demo wave schedule shared by the entry script and tests.

    The level document at ``levels/demo.toml`` is the single source of truth.
    This wrapper keeps the existing import path while the TOML loader owns
    parsing and validation.
    """
    from grid_td.levels import load_demo_level

    return load_demo_level().waves

