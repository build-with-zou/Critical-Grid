"""Deterministic single-tower strength baselines.

These tests are intentionally balance-sensitive. When tower or enemy numbers
change, update the expected time-to-kill and shot counts in the same commit so
the combat baseline stays reviewable.
"""

from dataclasses import dataclass
import unittest

from grid_td.enemies import create_enemy
from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


@dataclass(frozen=True)
class DuelResult:
    time_to_kill: float | None
    shots: int
    remaining_hp: float


def run_duel(
    tower_kind: str,
    enemy_kind: str,
    *,
    tower_position: Position = Position(30, 6),
    enemy_progress: float = 30.0,
    step_seconds: float = 0.05,
    timeout: float = 60.0,
) -> DuelResult:
    """Run one stationary enemy against one connected tower.

    The enemy is placed at a fixed route progress, so it cannot leave range or
    reach the core. Time-to-kill therefore measures only the tower's attack
    cadence and the enemy's effective health under the current damage rules.
    """
    game = GameState(create_demo_map())
    game.build(tower_kind, tower_position)
    game.start_next_wave()
    game.wave_runner = None

    enemy = create_enemy(enemy_kind)
    enemy.path_progress = enemy_progress
    enemy.speed = 0.0
    game.enemies = [enemy]

    elapsed = 0.0
    shots = 0
    last_hp = enemy.hp
    # Process events scheduled at logical time zero before advancing the clock.
    game.step(0.0)
    if enemy.hp < last_hp:
        shots += 1
        last_hp = enemy.hp

    while enemy.is_alive and elapsed + 1e-9 < timeout:
        game.step(step_seconds)
        elapsed += step_seconds
        if enemy.hp < last_hp:
            shots += 1
            last_hp = enemy.hp

    return DuelResult(
        time_to_kill=elapsed if not enemy.is_alive else None,
        shots=shots,
        remaining_hp=enemy.hp,
    )


class SingleTargetStrengthTest(unittest.TestCase):
    def test_gun_tower_vs_basic(self) -> None:
        result = run_duel("gun_tower", "basic")

        self.assertAlmostEqual(result.time_to_kill, 2.0, places=6)
        self.assertEqual(result.shots, 3)

    def test_gun_tower_vs_armored(self) -> None:
        result = run_duel("gun_tower", "armored")

        self.assertAlmostEqual(result.time_to_kill, 11.0, places=6)
        self.assertEqual(result.shots, 12)

    def test_cannon_tower_vs_basic(self) -> None:
        result = run_duel("cannon_tower", "basic")

        self.assertAlmostEqual(result.time_to_kill, 2.0, places=6)
        self.assertEqual(result.shots, 2)

    def test_cannon_tower_vs_armored(self) -> None:
        result = run_duel("cannon_tower", "armored")

        self.assertAlmostEqual(result.time_to_kill, 6.0, places=6)
        self.assertEqual(result.shots, 4)

    def test_slow_tower_vs_basic(self) -> None:
        result = run_duel("slow_tower", "basic")

        self.assertAlmostEqual(result.time_to_kill, 13.5, places=6)
        self.assertEqual(result.shots, 10)

    def test_slow_tower_vs_armored(self) -> None:
        result = run_duel("slow_tower", "armored")

        self.assertAlmostEqual(result.time_to_kill, 34.5, places=6)
        self.assertEqual(result.shots, 24)


if __name__ == "__main__":
    unittest.main()
