"""Coverage for priority-based allocation of connected power demand."""

import unittest

from grid_td.buildings import PowerPriority
from grid_td.game_state import GameState
from grid_td.map import GridMap
from grid_td.position import Footprint, Position


def make_map() -> GridMap:
    mine_anchor = Position(3, 3)
    return GridMap(
        width=12,
        height=12,
        route=(Position(0, 0),),
        core_position=Position(0, 0),
        mine_positions=frozenset(Footprint(3, 3).cells(mine_anchor)),
        high_ground_positions=frozenset(),
        illegal_ground_positions=frozenset(),
    )


class PowerPriorityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game = GameState(make_map(), gold=1000)
        self.gun = self.game.build("gun_tower", Position(3, 0))
        self.cannon = self.game.build("cannon_tower", Position(6, 0))
        self.slow = self.game.build("slow_tower", Position(0, 3))
        self.mine = self.game.build("mine", Position(3, 3))

    def test_high_priority_towers_are_served_before_low_priority_mine(self) -> None:
        self.assertEqual(self.gun.power_priority, PowerPriority.HIGH)
        self.assertEqual(self.mine.power_priority, PowerPriority.LOW)
        self.assertAlmostEqual(self.gun.power_efficiency, 10 / 12)
        self.assertAlmostEqual(self.cannon.power_efficiency, 10 / 12)
        self.assertAlmostEqual(self.slow.power_efficiency, 10 / 12)
        self.assertEqual(self.mine.power_efficiency, 0.0)
        self.assertEqual(self.mine.efficiency, 0.0)

    def test_same_priority_shares_shortage_proportionally(self) -> None:
        self.game.set_power_priority(self.mine.id, PowerPriority.HIGH)

        for building in (self.gun, self.cannon, self.slow, self.mine):
            self.assertAlmostEqual(building.power_efficiency, 10 / 13)

    def test_priority_change_recalculates_and_is_in_snapshot(self) -> None:
        self.game.set_power_priority(self.gun.id, "low")
        self.assertEqual(self.gun.power_priority, PowerPriority.LOW)
        self.assertEqual(self.gun.power_efficiency, 0.25)

        snapshot = self.game.cell_snapshot(self.gun.position).building
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.power_priority, PowerPriority.LOW)
        self.assertEqual(snapshot.power_efficiency, 0.25)

    def test_priority_rejects_sources_and_invalid_values_without_mutation(self) -> None:
        core = self.game.building_at(self.game.grid_map.core_position)
        assert core is not None
        old_priority = self.gun.power_priority
        with self.assertRaises(ValueError):
            self.game.set_power_priority(core.id, PowerPriority.HIGH)
        with self.assertRaises(ValueError):
            self.game.set_power_priority(self.gun.id, "urgent")
        self.assertEqual(self.gun.power_priority, old_priority)

    def test_priority_change_keeps_all_other_building_state(self) -> None:
        before_gold = self.game.gold
        before_position = self.gun.position
        self.game.set_power_priority(self.gun.id, PowerPriority.LOW)
        self.assertEqual(self.game.gold, before_gold)
        self.assertEqual(self.gun.position, before_position)
        self.assertEqual(self.cannon.power_priority, PowerPriority.HIGH)


if __name__ == "__main__":
    unittest.main()
