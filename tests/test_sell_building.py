"""Selling must be a validated public command with a fixed refund policy.

These tests protect the GUI-facing `sell_building()` command: its gold refund
and grid recalculation on success, and its rejection rules without side effects.
"""

import unittest
from collections.abc import Callable

from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


class SellBuildingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game = GameState(create_demo_map())

    def assert_rejected_without_changes(self, operation: Callable[[], object]) -> None:
        before = self.game.snapshot()
        with self.assertRaises(ValueError):
            operation()
        self.assertEqual(self.game.snapshot(), before)

    def test_sell_building_refunds_seventy_percent_of_cost(self) -> None:
        tower = self.game.build("gun_tower", Position(30, 6))
        gold_before = self.game.gold

        refund = self.game.sell_building(tower.id)

        self.assertEqual(refund, 21)
        self.assertEqual(self.game.gold, gold_before + 21)
        self.assertIsNone(self.game.building_at(Position(30, 6)))

    def test_sell_building_recalculates_power_for_downstream_buildings(self) -> None:
        plant = self.game.build("power_plant", Position(30, 6))
        tower = self.game.build("gun_tower", Position(30, 12))
        self.assertTrue(tower.connected_to_grid)

        self.game.sell_building(plant.id)

        self.assertFalse(tower.connected_to_grid)
        self.assertEqual(self.game.latest_power_report.total_demand, 0)

    def test_sell_building_accepts_mines_and_nodes(self) -> None:
        mine = self.game.build("mine", Position(6, 3))
        node = self.game.build("power_node", Position(30, 9))

        self.assertEqual(self.game.sell_building(mine.id), 24)
        self.assertEqual(self.game.sell_building(node.id), 10)
        self.assertIsNone(self.game.building_at(Position(6, 3)))
        self.assertIsNone(self.game.building_at(Position(30, 9)))

    def test_sell_building_rejects_the_core(self) -> None:
        core_id = self.game.cell_snapshot(Position(30, 3)).building.id
        self.assert_rejected_without_changes(lambda: self.game.sell_building(core_id))

    def test_sell_building_rejects_invalid_or_missing_ids(self) -> None:
        tower = self.game.build("gun_tower", Position(30, 6))
        for building_id in (0, -1, True, False, 1.0, "1", None, 999):
            with self.subTest(building_id=building_id):
                self.assert_rejected_without_changes(
                    lambda: self.game.sell_building(building_id)
                )
        # The sold tower ID is no longer valid.
        self.game.sell_building(tower.id)
        self.assert_rejected_without_changes(lambda: self.game.sell_building(tower.id))

    def test_sell_building_rejects_finished_or_destroyed_core(self) -> None:
        tower = self.game.build("gun_tower", Position(30, 6))
        self.game.result_message = "Victory. All waves cleared."
        self.assert_rejected_without_changes(lambda: self.game.sell_building(tower.id))

        self.game.result_message = ""
        self.game.core_hp = 0
        self.assert_rejected_without_changes(lambda: self.game.sell_building(tower.id))


if __name__ == "__main__":
    unittest.main()
