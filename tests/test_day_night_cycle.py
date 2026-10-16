"""Public lifecycle coverage for planning days and combat nights."""

import unittest
from collections.abc import Callable

from grid_td.game_state import GamePhase, GameState
from grid_td.map import create_demo_map
from grid_td.position import Position
from grid_td.renderer import TextRenderer


class DayNightCycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game = GameState(create_demo_map())

    def assert_rejected_without_changes(self, operation: Callable[[], object]) -> None:
        before = self.game.snapshot()
        runner = self.game.wave_runner
        if runner is not None:
            runner_time = runner.elapsed_seconds
            spawned_counts = runner.spawned_counts.copy()

        with self.assertRaises(ValueError):
            operation()

        self.assertEqual(self.game.snapshot(), before)
        self.assertIs(self.game.wave_runner, runner)
        if runner is not None:
            self.assertEqual(runner.elapsed_seconds, runner_time)
            self.assertEqual(runner.spawned_counts, spawned_counts)

    def finish_night(self) -> None:
        """Drive real waves with the intended 20 Hz logical update rate."""
        for _ in range(2000):
            self.game.step(0.05)
            if self.game.waiting_for_next_wave:
                return
            self.assertFalse(self.game.is_finished)
        self.fail("The night did not clear within 100 logical seconds.")

    def test_new_game_is_a_planning_day(self) -> None:
        status = self.game.snapshot().status

        self.assertEqual(status.phase, GamePhase.DAY)
        self.assertEqual(status.phase.value, "day")
        self.assertEqual(status.wave_index, 0)
        self.assertEqual(status.current_wave_name, "Wave 1")
        self.assertEqual(status.elapsed_seconds, 0.0)
        self.assertFalse(status.is_finished)
        self.assertFalse(status.waiting_for_next_wave)
        self.assertIsNone(self.game.wave_runner)
        self.assertEqual(self.game.enemies, [])
        self.assertIn("Phase=day", TextRenderer().render(self.game))

    def test_day_freezes_clock_and_tower_timers(self) -> None:
        tower = self.game.build("gun_tower", Position(10, 2))
        tower.cooldown_remaining = 0.75  # Seed a pending cooldown for this fixture.
        self.game.overload_tower(tower.id, 5.25)
        before = self.game.snapshot()

        for seconds in (0, 0.05, 1.0, 1000):
            self.game.step(seconds)

        self.assertEqual(self.game.snapshot(), before)
        self.assertIsNone(self.game.wave_runner)
        self.assertEqual(tower.overload_seconds_remaining, 5.25)
        self.assertEqual(tower.cooldown_remaining, 0.75)

    def test_planning_still_allows_building_and_intel(self) -> None:
        gold_before = self.game.gold

        tower = self.game.build("gun_tower", Position(10, 2))
        briefing = self.game.buy_wave_intel()

        self.assertEqual(self.game.phase, GamePhase.DAY)
        self.assertEqual(self.game.gold, gold_before - tower.cost - 8)
        self.assertTrue(tower.connected_to_grid)
        self.assertEqual(briefing, "Basic enemies.")
        self.assertEqual(self.game.elapsed_seconds, 0.0)

    def test_start_night_only_changes_phase_and_creates_runner(self) -> None:
        before = self.game.snapshot()

        self.assertIsNone(self.game.start_next_wave())

        status = self.game.snapshot().status
        self.assertEqual(status.phase, GamePhase.NIGHT)
        self.assertEqual(status.wave_index, 0)
        self.assertEqual(status.gold, before.status.gold)
        self.assertEqual(status.debt, before.status.debt)
        self.assertEqual(status.elapsed_seconds, 0.0)
        self.assertEqual(self.game.wave_runner.elapsed_seconds, 0.0)
        self.assertEqual(self.game.enemies, [])
        self.assert_rejected_without_changes(self.game.start_next_wave)

        self.game.step(0)

        self.assertEqual(len(self.game.enemies), 1)
        self.assertEqual(self.game.enemies[0].path_progress, 0.0)
        self.assertEqual(self.game.elapsed_seconds, 0.0)

    def test_building_and_intel_keep_existing_night_behavior(self) -> None:
        self.game.start_next_wave()
        gold_before = self.game.gold

        tower = self.game.build("gun_tower", Position(10, 2))
        self.assertEqual(self.game.buy_wave_intel(), "Basic enemies.")

        self.assertEqual(self.game.phase, GamePhase.NIGHT)
        self.assertEqual(self.game.gold, gold_before - tower.cost - 8)

    def test_night_advances_cooldown_and_overload_with_shared_delta(self) -> None:
        # This connected tower is out of range of the entrance, so its timer
        # changes can be observed without an attack resetting the cooldown.
        tower = self.game.build("gun_tower", Position(10, 2))
        tower.cooldown_remaining = 0.5
        self.game.overload_tower(tower.id, 5.0)
        self.game.start_next_wave()

        self.game.step(0.05)

        self.assertAlmostEqual(self.game.elapsed_seconds, 0.05)
        self.assertAlmostEqual(self.game.wave_runner.elapsed_seconds, 0.05)
        self.assertAlmostEqual(tower.overload_seconds_remaining, 4.95)
        self.assertAlmostEqual(tower.cooldown_remaining, 0.45)
        self.assertAlmostEqual(self.game.enemies[0].path_progress, 0.75 * 0.05)

    def test_day_cannot_settle_a_wave(self) -> None:
        self.assert_rejected_without_changes(self.game.end_wave)

    def test_settlement_enters_day_and_waits_for_explicit_start(self) -> None:
        self.game.start_next_wave()
        self.finish_night()
        self.assertEqual(self.game.phase, GamePhase.NIGHT)

        self.game.end_wave()
        tower = self.game.build("gun_tower", Position(10, 2))
        self.game.overload_tower(tower.id, 4.0)
        before = self.game.snapshot()

        self.game.step(100)

        self.assertEqual(self.game.snapshot(), before)
        self.assertEqual(self.game.phase, GamePhase.DAY)
        self.assertEqual(self.game.wave_index, 1)
        self.assertIsNone(self.game.wave_runner)
        self.assertEqual(tower.overload_seconds_remaining, 4.0)
        self.assert_rejected_without_changes(self.game.end_wave)

        self.game.start_next_wave()
        self.game.step(0.05)

        self.assertEqual(self.game.phase, GamePhase.NIGHT)
        self.assertEqual(self.game.wave_runner.wave, self.game.waves[1])
        self.assertAlmostEqual(self.game.wave_runner.elapsed_seconds, 0.05)
        self.assertAlmostEqual(self.game.elapsed_seconds, before.status.elapsed_seconds + 0.05)

    def test_all_four_days_and_nights_end_in_victory(self) -> None:
        self.game = GameState(create_demo_map(), core_hp=100)

        for index in range(4):
            with self.subTest(night=index + 1):
                self.assertEqual(self.game.phase, GamePhase.DAY)
                self.assertEqual(self.game.wave_index, index)
                self.game.start_next_wave()
                self.finish_night()
                self.assertEqual(self.game.phase, GamePhase.NIGHT)
                self.assertFalse(self.game.is_finished)
                self.game.end_wave()

        status = self.game.snapshot().status
        self.assertEqual(status.phase, GamePhase.VICTORY)
        self.assertTrue(status.is_finished)
        self.assertFalse(status.waiting_for_next_wave)
        self.assertEqual(status.wave_index, 4)
        self.assertEqual(status.result_message, "Victory. All waves cleared.")
        self.assert_rejected_without_changes(self.game.start_next_wave)
        self.assert_rejected_without_changes(self.game.end_wave)

        before = self.game.snapshot()
        self.game.step(1.0)
        self.assertEqual(self.game.snapshot(), before)

    def test_core_destruction_enters_defeat_without_settlement(self) -> None:
        self.game = GameState(create_demo_map(), core_hp=1)
        self.game.start_next_wave()
        gold_before = self.game.gold

        self.game.step(30.0)

        status = self.game.snapshot().status
        self.assertEqual(status.phase, GamePhase.DEFEAT)
        self.assertTrue(status.is_finished)
        self.assertEqual(status.core_hp, 0)
        self.assertEqual(status.wave_index, 0)
        self.assertEqual(status.gold, gold_before)
        self.assertFalse(status.waiting_for_next_wave)
        self.assert_rejected_without_changes(self.game.start_next_wave)
        self.assert_rejected_without_changes(self.game.end_wave)

        before = self.game.snapshot()
        self.game.step(1.0)
        self.assertEqual(self.game.snapshot(), before)

    def test_invalid_day_steps_still_raise_without_changes(self) -> None:
        for seconds in (-0.05, True, "0.05", float("nan"), float("inf")):
            with self.subTest(seconds=seconds):
                self.assert_rejected_without_changes(lambda: self.game.step(seconds))

    def test_zero_health_cannot_wait_safely_in_day(self) -> None:
        self.game = GameState(create_demo_map(), core_hp=0)

        self.game.step(0.05)

        self.assertEqual(self.game.snapshot().status.phase, GamePhase.DEFEAT)
        self.assertTrue(self.game.is_finished)
        self.assertEqual(self.game.elapsed_seconds, 0.0)
        self.assertIsNone(self.game.wave_runner)


if __name__ == "__main__":
    unittest.main()
