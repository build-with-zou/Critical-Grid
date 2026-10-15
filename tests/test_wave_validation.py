"""Regression coverage for legal and rejected wave transitions."""

import unittest
from collections.abc import Callable

from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


class WaveValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game = GameState(create_demo_map())

    def assert_rejected_without_changes(self, operation: Callable[[], object]) -> None:
        """A rejected command must preserve display and scheduler state."""
        game = self.game
        before = game.snapshot()
        runner = game.wave_runner
        if runner is not None:
            elapsed = runner.elapsed_seconds
            counts = runner.spawned_counts.copy()

        with self.assertRaises(ValueError):
            operation()

        self.assertEqual(game.snapshot(), before)
        self.assertIs(game.wave_runner, runner)
        if runner is not None:
            self.assertEqual(runner.elapsed_seconds, elapsed)
            self.assertEqual(runner.spawned_counts, counts)

    def test_cannot_settle_before_spawning_finishes(self) -> None:
        self.assertFalse(self.game.wave_runner.is_complete)
        self.assert_rejected_without_changes(self.game.end_wave)

    def test_cannot_settle_while_enemies_remain(self) -> None:
        self.game.step(8.0)

        self.assertTrue(self.game.wave_runner.is_complete)
        self.assertTrue(self.game.enemies)
        self.assert_rejected_without_changes(self.game.end_wave)

    def test_cannot_restart_active_or_unsettled_wave(self) -> None:
        for label, seconds in (("initial", 0.0), ("active", 1.0), ("cleared", 30.0)):
            with self.subTest(state=label):
                self.game = GameState(create_demo_map())
                if seconds:
                    self.game.step(seconds)
                if label == "cleared":
                    self.assertTrue(self.game.waiting_for_next_wave)
                self.assert_rejected_without_changes(self.game.start_next_wave)

    def test_settlement_pays_income_interest_and_repairs_only_once(self) -> None:
        game = self.game
        tower = game.build("gun_tower", Position(10, 2))
        game.build("power_node", Position(10, 3))
        game.build("power_node", Position(10, 4))
        game.build("power_node", Position(10, 5))
        game.build("power_node", Position(9, 5))
        game.build("mine", Position(8, 5))
        game.core_overdraft()
        game.overload_tower(tower.id)
        game.step(30.0)
        self.assertTrue(game.waiting_for_next_wave)
        self.assertTrue(tower.needs_repair)
        gold_before = game.gold
        debt_before = game.debt

        message = game.end_wave()

        self.assertIn("Mine income +12, interest -8, repairs -5", message)
        self.assertEqual(game.gold, gold_before + 12 - 8 - 5)
        self.assertEqual(game.debt, debt_before)
        self.assertFalse(tower.needs_repair)
        self.assertEqual(game.wave_index, 1)
        self.assertIsNone(game.wave_runner)
        self.assertFalse(game.waiting_for_next_wave)
        self.assert_rejected_without_changes(game.end_wave)

        before_start = game.snapshot()
        game.start_next_wave()

        self.assertEqual(game.snapshot(), before_start)
        self.assertEqual(game.wave_runner.wave, game.waves[1])
        self.assertEqual(game.wave_runner.elapsed_seconds, 0.0)
        self.assertEqual(game.wave_runner.spawned_counts, [0, 0])
        self.assert_rejected_without_changes(game.start_next_wave)
        self.assert_rejected_without_changes(game.end_wave)

    def test_defeat_cannot_be_settled_or_restarted(self) -> None:
        self.game = GameState(create_demo_map(), core_hp=1)
        self.game.step(30.0)

        self.assertTrue(self.game.is_finished)
        self.assertFalse(self.game.enemies)
        self.assertFalse(self.game.waiting_for_next_wave)
        self.assert_rejected_without_changes(self.game.end_wave)
        self.assert_rejected_without_changes(self.game.start_next_wave)
        self.assertEqual(self.game.result_message, "Defeat. The core was destroyed.")

    def test_destroyed_core_without_result_cannot_transition(self) -> None:
        self.game = GameState(create_demo_map(), core_hp=0)

        self.assert_rejected_without_changes(self.game.end_wave)
        self.assert_rejected_without_changes(self.game.start_next_wave)

    def test_all_waves_finish_only_after_final_settlement(self) -> None:
        # Extra health lets real enemies finish their routes without defenses.
        self.game = GameState(create_demo_map(), core_hp=100)
        game = self.game

        for index in range(len(game.waves)):
            with self.subTest(wave=index):
                self.assertEqual(game.wave_index, index)
                for _ in range(100):
                    game.step(1.0)
                    if game.waiting_for_next_wave:
                        break
                self.assertTrue(game.waiting_for_next_wave)
                self.assertFalse(game.is_finished)

                game.end_wave()

                self.assertEqual(game.wave_index, index + 1)
                self.assertIsNone(game.wave_runner)
                if index < len(game.waves) - 1:
                    self.assertFalse(game.is_finished)
                    game.start_next_wave()

        self.assertGreater(game.core_hp, 0)
        self.assertTrue(game.is_finished)
        self.assertFalse(game.waiting_for_next_wave)
        self.assertEqual(game.result_message, "Victory. All waves cleared.")
        self.assert_rejected_without_changes(game.end_wave)
        self.assert_rejected_without_changes(game.start_next_wave)


if __name__ == "__main__":
    unittest.main()
