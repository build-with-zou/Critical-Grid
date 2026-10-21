"""Regression coverage for condition-based building efficiency."""

import unittest

from grid_td.buildings import Building
from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


class HealthEfficiencyTest(unittest.TestCase):
    def make_building(self, hp: int) -> Building:
        """Create a 100-HP generic building for exact percentage thresholds."""
        return Building(
            id=1,
            name="Test Building",
            position=Position(0, 0),
            cost=0,
            max_hp=100,
            current_hp=hp,
        )

    def test_ninety_percent_and_above_has_no_condition_penalty(self) -> None:
        for hp in (100, 99, 90):
            with self.subTest(hp=hp):
                self.assertEqual(self.make_building(hp).health_efficiency, 1.0)

    def test_each_lower_ten_percent_band_reduces_condition_efficiency(self) -> None:
        expected = {
            89: 0.9,
            80: 0.9,
            79: 0.8,
            70: 0.8,
            69: 0.7,
            60: 0.7,
            59: 0.6,
            50: 0.6,
            49: 0.5,
            40: 0.5,
            39: 0.4,
            30: 0.4,
            29: 0.3,
            20: 0.3,
            19: 0.2,
            10: 0.2,
            9: 0.1,
            1: 0.1,
            0: 0.0,
        }
        for hp, efficiency in expected.items():
            with self.subTest(hp=hp):
                self.assertEqual(self.make_building(hp).health_efficiency, efficiency)

    def test_health_and_power_efficiencies_are_multiplied(self) -> None:
        game = GameState(create_demo_map())
        gun = game.build("gun_tower", Position(30, 6))
        game.build("power_node", Position(30, 9))
        cannon = game.build("cannon_tower", Position(24, 9))
        slow = game.build("slow_tower", Position(30, 12))
        self.assertAlmostEqual(game.latest_power_report.efficiency, 10 / 12)

        gun.take_damage(gun.max_hp // 2)
        game.recalculate_power()

        self.assertEqual(gun.health_efficiency, 0.6)
        self.assertAlmostEqual(gun.efficiency, (10 / 12) * 0.6)
        self.assertAlmostEqual(cannon.efficiency, 10 / 12)
        self.assertAlmostEqual(slow.efficiency, 10 / 12)

    def test_repair_restores_condition_efficiency_without_changing_power_efficiency(self) -> None:
        game = GameState(create_demo_map())
        gun = game.build("gun_tower", Position(30, 6))
        gun.take_damage(gun.max_hp // 2)
        game.recalculate_power()
        power_efficiency = game.latest_power_report.efficiency
        damaged_efficiency = gun.efficiency

        game.repair_building(gun.id)

        self.assertEqual(gun.health_efficiency, 1.0)
        self.assertAlmostEqual(gun.efficiency, power_efficiency)
        self.assertGreater(gun.efficiency, damaged_efficiency)

    def test_destroyed_building_has_zero_effective_efficiency(self) -> None:
        game = GameState(create_demo_map())
        gun = game.build("gun_tower", Position(30, 6))
        gun.take_damage(gun.hp)
        game.recalculate_power()

        self.assertEqual(gun.health_efficiency, 0.0)
        self.assertEqual(gun.efficiency, 0.0)


if __name__ == "__main__":
    unittest.main()
