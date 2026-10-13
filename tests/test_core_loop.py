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
from grid_td.renderer import TextRenderer


class CoreLoopTest(unittest.TestCase):
    """Verify core behavior when the state layer connects domain objects."""

    def test_building_updates_power_grid(self) -> None:
        """A plant and adjacent tower should connect and get positive efficiency."""
        game = GameState(create_demo_map())

        game.build("power_plant", Position(10, 2))
        tower = game.build("gun_tower", Position(10, 3))

        self.assertTrue(tower.connected_to_grid)
        self.assertGreater(tower.efficiency, 0)

    def test_disconnected_building_has_zero_efficiency(self) -> None:
        """A building outside the adjacent grid should render as unpowered."""
        game = GameState(create_demo_map())

        tower = game.build("gun_tower", Position(0, 1))

        self.assertFalse(tower.connected_to_grid)
        self.assertEqual(tower.efficiency, 0.0)
        self.assertEqual(game.latest_power_report.connected_count, 1)

    def test_power_shortage_reduces_connected_efficiency(self) -> None:
        """Connected demand above supply should lower shared efficiency."""
        game = GameState(create_demo_map())

        game.build("gun_tower", Position(10, 2))
        game.build("slow_tower", Position(10, 3))
        cannon = game.build("cannon_tower", Position(10, 4))

        report = game.latest_power_report
        self.assertEqual(report.total_supply, 10)
        self.assertEqual(report.total_demand, 12)
        self.assertAlmostEqual(report.efficiency, 10 / 12)
        self.assertAlmostEqual(cannon.efficiency, 10 / 12)

    def test_high_ground_increases_tower_range(self) -> None:
        """Building a tower on high ground should apply the range bonus."""
        game = GameState(create_demo_map())

        tower = game.build("gun_tower", Position(4, 2))

        self.assertEqual(tower.range, 3)

    def test_core_overdraft_adds_gold_and_debt(self) -> None:
        """Core overdraft should add both gold and debt."""
        game = GameState(create_demo_map())
        gold_before = game.gold

        game.core_overdraft(40)

        self.assertEqual(game.gold, gold_before + 40)
        self.assertGreater(game.debt, 0)

    def test_buy_wave_intel_spends_gold_and_requires_gold(self) -> None:
        """Buying intel should expose the briefing and enforce its price."""
        game = GameState(create_demo_map())

        briefing = game.buy_wave_intel()

        self.assertEqual(briefing, "Basic enemies.")
        self.assertEqual(game.gold, 172)

        poor_game = GameState(create_demo_map(), gold=0)
        with self.assertRaises(ValueError):
            poor_game.buy_wave_intel()

    def test_building_on_illegal_position(self) -> None:
        """Build placement rules should reject blocked or otherwise invalid cells."""
        game = GameState(create_demo_map())

        invalid_cases = (
            ("blocked terrain", "gun_tower", Position(0, 0)),
            ("enemy route", "gun_tower", Position(0, 4)),
            ("core position", "gun_tower", Position(10, 1)),
            ("mine outside mine site", "mine", Position(0, 1)),
            ("non-mine on mine site", "gun_tower", Position(2, 1)),
        )

        for label, kind, position in invalid_cases:
            with self.subTest(label=label, kind=kind, position=position):
                with self.assertRaises(ValueError):
                    game.build(kind, position)

        occupied_position = Position(10, 2)
        game.build("power_plant", occupied_position)

        with self.subTest(label="occupied position"):
            with self.assertRaises(ValueError):
                game.build("gun_tower", occupied_position)

    def test_building_requires_enough_gold(self) -> None:
        """Build placement should fail cleanly when the player cannot pay."""
        game = GameState(create_demo_map(), gold=0)

        with self.assertRaises(ValueError):
            game.build("gun_tower", Position(0, 1))

        self.assertIsNone(game.building_at(Position(0, 1)))

    def test_text_renderer_shows_illegal_ground(self) -> None:
        """Text rendering should expose blocked terrain for debugging and parity with GUI."""
        game = GameState(create_demo_map())
        rendered = TextRenderer().render(game)
        first_map_row = rendered.splitlines()[1]

        self.assertEqual(first_map_row, "##...##.....")

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

