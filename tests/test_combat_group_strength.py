"""Deterministic group-clear baselines for splash and single-target towers."""

from dataclasses import dataclass
import unittest

from grid_td.enemies import create_enemy
from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


@dataclass(frozen=True)
class GroupResult:
    time_to_clear: float | None
    remaining_enemies: int


def run_group(
    tower_kind: str,
    *,
    step_seconds: float = 0.05,
    timeout: float = 60.0,
) -> GroupResult:
    """Run two stationary basic enemies through one connected tower.

    The lead enemy is exactly three world units ahead of the follower, placing
    the follower on the cannon splash boundary. This makes splash value visible
    without depending on spawn timing or movement.
    """
    game = GameState(create_demo_map())
    game.build(tower_kind, Position(30, 6))
    game.start_next_wave()
    game.wave_runner = None

    lead = create_enemy("basic")
    lead.path_progress = 34.0
    lead.speed = 0.0
    follower = create_enemy("basic")
    follower.path_progress = 31.0
    follower.speed = 0.0
    game.enemies = [lead, follower]

    elapsed = 0.0
    # Process time-zero attacks first so measured clear time reflects the
    # continuous attack cadence rather than the first fixed-step boundary.
    game.step(0.0)
    while game.enemies and elapsed + 1e-9 < timeout:
        game.step(step_seconds)
        elapsed += step_seconds

    return GroupResult(
        time_to_clear=elapsed if not game.enemies else None,
        remaining_enemies=len(game.enemies),
    )


class GroupStrengthTest(unittest.TestCase):
    def test_cannon_clears_two_basics_faster_than_gun(self) -> None:
        cannon = run_group("cannon_tower")
        gun = run_group("gun_tower")

        self.assertAlmostEqual(cannon.time_to_clear, 4.0, places=6)
        self.assertEqual(cannon.remaining_enemies, 0)
        self.assertAlmostEqual(gun.time_to_clear, 5.0, places=6)
        self.assertEqual(gun.remaining_enemies, 0)
        self.assertLess(cannon.time_to_clear, gun.time_to_clear)


if __name__ == "__main__":
    unittest.main()
