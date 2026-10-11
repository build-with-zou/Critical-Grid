from __future__ import annotations

from dataclasses import dataclass

from grid_td.enemies import Enemy, create_enemy


@dataclass(frozen=True)
class SpawnGroup:
    enemy_kind: str
    count: int
    interval_seconds: float
    start_delay_seconds: float = 0.0


@dataclass(frozen=True)
class Wave:
    name: str
    briefing: str
    groups: tuple[SpawnGroup, ...]


class WaveRunner:
    def __init__(self, wave: Wave) -> None:
        self.wave = wave
        self.elapsed_seconds = 0.0
        self.spawned_counts = [0 for _ in wave.groups]

    @property
    def is_complete(self) -> bool:
        return all(
            spawned >= group.count
            for spawned, group in zip(self.spawned_counts, self.wave.groups)
        )

    def step(self, seconds: float) -> list[Enemy]:
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

