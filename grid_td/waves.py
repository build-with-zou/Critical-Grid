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


@dataclass(frozen=True)
class SpawnGroup:
    """Timed spawn configuration for one enemy type."""

    enemy_kind: str  # Template key passed to create_enemy().
    count: int  # Maximum number of enemies spawned by this group.
    interval_seconds: float  # Logical interval between enemies in this group.
    start_delay_seconds: float = 0.0  # First-spawn delay from wave start.


@dataclass(frozen=True)
class Wave:
    """Static configuration and player-facing briefing for one wave."""

    name: str  # Wave name shown in the status line.
    briefing: str  # Description returned by purchased intel.
    groups: tuple[SpawnGroup, ...]  # Spawn groups advanced in parallel.


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

                spawned_enemies.append(create_enemy(group.enemy_kind))
                spawned += 1

            self.spawned_counts[index] = spawned

        return spawned_enemies


def create_demo_waves() -> tuple[Wave, ...]:
    """Create the four demo waves used by the entry script and tests.

    Wave parameters are current prototype balance data and should not be
    implicitly changed by scheduling logic. Register new enemy types in
    `grid_td.enemies.create_enemy()` first; after adding waves, also check
    `GameState` victory conditions and demo runtime.
    """
    return (
        Wave(
            name="Wave 1",
            briefing="Basic enemies.",
            groups=(SpawnGroup("basic", count=5, interval_seconds=1.5),),
        ),
        Wave(
            name="Wave 2",
            briefing="Fast enemies mixed with basic enemies.",
            groups=(
                SpawnGroup("basic", count=5, interval_seconds=1.2),
                SpawnGroup("fast", count=3, interval_seconds=1.8, start_delay_seconds=2.0),
            ),
        ),
        Wave(
            name="Wave 3",
            briefing="Armored enemies test sustained damage.",
            groups=(
                SpawnGroup("basic", count=4, interval_seconds=1.0),
                SpawnGroup("armored", count=3, interval_seconds=2.5, start_delay_seconds=1.0),
            ),
        ),
        Wave(
            name="Wave 4",
            briefing="Saboteurs appear. Protect the grid.",
            groups=(
                SpawnGroup("fast", count=4, interval_seconds=1.2),
                SpawnGroup("saboteur", count=3, interval_seconds=2.0, start_delay_seconds=1.5),
            ),
        ),
    )

