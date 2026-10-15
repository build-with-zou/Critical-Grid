"""Emergency commands must reject invalid requests without side effects."""

import unittest
from collections.abc import Callable

from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


class EmergencyValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game = GameState(create_demo_map())
        self.tower = self.game.build("gun_tower", Position(10, 2))

    def assert_rejected_without_changes(self, operation: Callable[[], object]) -> None:
        before = self.game.snapshot()
        overload_remaining = self.tower.overload_seconds_remaining

        with self.assertRaises(ValueError):
            operation()

        self.assertEqual(self.game.snapshot(), before)
        self.assertEqual(self.tower.overload_seconds_remaining, overload_remaining)

    def test_default_overdraft_keeps_existing_gold_and_debt_rules(self) -> None:
        gold_before = self.game.gold

        self.assertIsNone(self.game.core_overdraft())

        self.assertEqual(self.game.gold, gold_before + 40)
        self.assertEqual(self.game.debt, 54)

    def test_positive_integer_overdraft_adds_to_existing_resources(self) -> None:
        for amount, debt_added in ((1, 1), (2, 3), (10, 14), (110, 148)):
            with self.subTest(amount=amount):
                gold_before = self.game.gold
                debt_before = self.game.debt

                self.game.core_overdraft(amount)

                self.assertEqual(self.game.gold, gold_before + amount)
                self.assertEqual(self.game.debt, debt_before + debt_added)

    def test_invalid_overdraft_amounts_do_not_change_state(self) -> None:
        # Check rejection even when debt and repair state already exist.
        self.game.overload_tower(self.tower.id)
        for amount in (0, -40, 40.0, 1.5, True, False, "40", None,
                       float("nan"), float("inf"), -float("inf"),
                       15 * 10 ** 307, 10 ** 1000):
            with self.subTest(amount=amount):
                self.assert_rejected_without_changes(
                    lambda: self.game.core_overdraft(amount)
                )

    def test_default_overload_keeps_existing_cost_and_duration(self) -> None:
        gold_before = self.game.gold

        self.assertIsNone(self.game.overload_tower(self.tower.id))

        self.assertEqual(self.tower.overload_seconds_remaining, 8.0)
        self.assertTrue(self.tower.needs_repair)
        self.assertEqual(self.game.debt, 10)
        self.assertEqual(self.game.gold, gold_before)

    def test_repeated_overload_charges_each_time_and_keeps_longer_duration(self) -> None:
        for seconds, remaining, debt in ((3.25, 3.25, 10), (2, 3.25, 20), (12, 12, 30)):
            with self.subTest(seconds=seconds):
                self.game.overload_tower(self.tower.id, seconds)

                self.assertEqual(self.tower.overload_seconds_remaining, remaining)
                self.assertTrue(self.tower.needs_repair)
                self.assertEqual(self.game.debt, debt)

    def test_invalid_duration_does_not_start_overload_or_charge_costs(self) -> None:
        for seconds in (0, -1, True, False, "8", None, float("nan"),
                        float("inf"), -float("inf"), 10 ** 1000):
            with self.subTest(seconds=seconds):
                self.assert_rejected_without_changes(
                    lambda: self.game.overload_tower(self.tower.id, seconds)
                )

    def test_invalid_duration_preserves_existing_overload(self) -> None:
        self.game.overload_tower(self.tower.id, 3.25)

        for seconds in (0, -1, "8", float("nan"), float("inf")):
            with self.subTest(seconds=seconds):
                self.assert_rejected_without_changes(
                    lambda: self.game.overload_tower(self.tower.id, seconds)
                )

    def test_invalid_tower_id_does_not_change_state(self) -> None:
        node = self.game.build("power_node", Position(10, 3))
        core_id = self.game.cell_snapshot(Position(10, 1)).building.id
        invalid_ids = (0, -1, 999, core_id, node.id, float(self.tower.id),
                       True, False, str(self.tower.id), None)
        for building_id in invalid_ids:
            with self.subTest(building_id=building_id):
                self.assert_rejected_without_changes(
                    lambda: self.game.overload_tower(building_id)
                )

    def test_finished_games_reject_both_emergency_commands(self) -> None:
        self.game.overload_tower(self.tower.id)
        for result in ("Victory. All waves cleared.", "Defeat. The core was destroyed."):
            with self.subTest(result=result):
                self.game.result_message = result
                self.assert_rejected_without_changes(self.game.core_overdraft)
                self.assert_rejected_without_changes(
                    lambda: self.game.overload_tower(self.tower.id)
                )

    def test_destroyed_core_without_result_rejects_emergency_commands(self) -> None:
        for hp in (0, -1):
            with self.subTest(core_hp=hp):
                self.game.core_hp = hp
                self.assert_rejected_without_changes(self.game.core_overdraft)
                self.assert_rejected_without_changes(
                    lambda: self.game.overload_tower(self.tower.id)
                )


if __name__ == "__main__":
    unittest.main()
