"""Regression coverage for build and wave-intel terminal-state rules."""

import unittest

from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


class BuildAndIntelValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game = GameState(create_demo_map())

    def test_build_rejects_finished_game_without_mutating_state(self) -> None:
        self.game.result_message = "Victory. All waves cleared."
        before = self.game.snapshot()
        next_id_before = self.game.next_building_id

        with self.assertRaises(ValueError):
            self.game.build("gun_tower", Position(0, 1))

        self.assertEqual(self.game.snapshot(), before)
        self.assertEqual(self.game.next_building_id, next_id_before)
        self.assertIsNone(self.game.building_at(Position(0, 1)))

    def test_build_rejects_destroyed_core_without_mutating_state(self) -> None:
        self.game.core_hp = 0
        before = self.game.snapshot()
        next_id_before = self.game.next_building_id

        with self.assertRaises(ValueError):
            self.game.build("gun_tower", Position(0, 1))

        self.assertEqual(self.game.snapshot(), before)
        self.assertEqual(self.game.next_building_id, next_id_before)

    def test_intel_still_charges_for_an_available_wave(self) -> None:
        gold_before = self.game.gold

        briefing = self.game.buy_wave_intel()

        self.assertEqual(briefing, "Basic enemies.")
        self.assertEqual(self.game.gold, gold_before - 8)

    def test_intel_is_free_when_no_waves_remain(self) -> None:
        self.game.wave_index = len(self.game.waves)
        gold_before = self.game.gold

        briefing = self.game.buy_wave_intel()

        self.assertEqual(briefing, "No incoming wave.")
        self.assertEqual(self.game.gold, gold_before)

    def test_intel_rejects_finished_game_without_mutating_state(self) -> None:
        self.game.result_message = "Victory. All waves cleared."
        before = self.game.snapshot()

        with self.assertRaises(ValueError):
            self.game.buy_wave_intel()

        self.assertEqual(self.game.snapshot(), before)

    def test_intel_rejects_destroyed_core_without_mutating_state(self) -> None:
        self.game.core_hp = 0
        before = self.game.snapshot()

        with self.assertRaises(ValueError):
            self.game.buy_wave_intel()

        self.assertEqual(self.game.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
