"""Minimal regression tests for the core loop.

These tests drive `GameState` directly and cover the most important
cross-module contracts in the current prototype: building should update the
power grid, core overdraft should increase both gold and debt, and the default
wave should advance without crashing. Tests use `create_demo_map()` as a fixed
fixture to avoid hiding real `PowerGrid`/`WaveRunner` collaboration behind
random maps or mocks.
"""

import unittest

from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


class CoreLoopTest(unittest.TestCase):
    """Verify core behavior when the state layer connects domain objects."""

    def test_building_updates_power_grid(self) -> None:
        """A plant and adjacent tower should connect and get positive efficiency."""
        game = GameState(create_demo_map())

        game.build("power_plant", Position(10, 2))
        tower = game.build("gun_tower", Position(10, 3))

        self.assertTrue(tower.connected_to_grid)
        self.assertGreater(tower.efficiency, 0)

    def test_core_overdraft_adds_gold_and_debt(self) -> None:
        """Core overdraft should add both gold and debt."""
        game = GameState(create_demo_map())
        gold_before = game.gold

        game.core_overdraft(40)

        self.assertEqual(game.gold, gold_before + 40)
        self.assertGreater(game.debt, 0)

    def test_demo_wave_can_advance_without_crashing(self) -> None:
        """The default map and basic defense should run for multiple steps."""
        game = GameState(create_demo_map())
        game.build("power_plant", Position(10, 2))
        game.build("gun_tower", Position(10, 3))

        for _ in range(20):
            game.step(1.0)

        self.assertGreaterEqual(game.core_hp, 0)


if __name__ == "__main__":
    unittest.main()

