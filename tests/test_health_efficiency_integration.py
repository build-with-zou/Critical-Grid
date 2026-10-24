"""Integration coverage for condition efficiency with settlement and snapshots."""

import unittest

from grid_td.game_state import GamePhase, GameState
from grid_td.map import create_demo_map
from grid_td.position import Position
from grid_td.waves import Wave


class HealthEfficiencyIntegrationTest(unittest.TestCase):
    def test_damaged_mine_settlement_uses_condition_efficiency(self) -> None:
        game = GameState(create_demo_map(), gold=500)
        mine = game.build("mine", Position(6, 3))
        for x in (12, 18, 24):
            game.build("power_node", Position(x, 3))
        mine.take_damage(4)
        game.recalculate_power()

        self.assertEqual(mine.health_efficiency, 0.6)
        self.assertEqual(mine.efficiency, 0.6)
        self.assertEqual(mine.collect_income(), 7)

        game.waves = (Wave("Test 1", "", ()), Wave("Test 2", "", ()))
        game.start_next_wave()
        game.step(0.0)
        gold_before = game.gold
        message = game.end_wave()

        self.assertIn("Mine income +7", message)
        self.assertEqual(game.gold, gold_before + 7)
        self.assertEqual(game.phase, GamePhase.DAY)

        spent = game.repair_building(mine.id)

        self.assertEqual(spent, 4)
        self.assertEqual(mine.health_efficiency, 1.0)
        self.assertEqual(mine.efficiency, 1.0)
        self.assertEqual(mine.collect_income(), 12)


class PowerPlantConditionTest(unittest.TestCase):
    def test_damaged_plant_supply_uses_health_band(self) -> None:
        game = GameState(create_demo_map(), gold=500)
        plant = game.build("power_plant", Position(30, 6))
        self.assertEqual(game.latest_power_report.total_supply, 20)

        plant.take_damage(2)
        game.recalculate_power()

        self.assertEqual(plant.health_efficiency, 0.9)
        self.assertEqual(plant.effective_power_supply, 9)
        self.assertEqual(game.latest_power_report.total_supply, 19)

        self.assertEqual(game.repair_building(plant.id), 2)
        self.assertEqual(plant.effective_power_supply, 10)
        self.assertEqual(game.latest_power_report.total_supply, 20)

    def test_core_supply_does_not_scale_with_damage(self) -> None:
        game = GameState(create_demo_map())
        core = game.building_at(game.grid_map.core_position)
        assert core is not None

        core.take_damage(15)
        game.recalculate_power()

        self.assertEqual(core.health_efficiency, 0.6)
        self.assertEqual(core.effective_power_supply, 10)
        self.assertEqual(game.latest_power_report.total_supply, 10)

    def test_destroyed_plant_supply_is_zero(self) -> None:
        game = GameState(create_demo_map())
        plant = game.build("power_plant", Position(30, 6))
        plant.take_damage(plant.hp)
        game.recalculate_power()

        self.assertEqual(plant.effective_power_supply, 0)
        self.assertEqual(game.latest_power_report.total_supply, 10)


class TowerConditionEfficiencyTest(unittest.TestCase):
    def test_damaged_tower_uses_final_efficiency_for_damage_and_speed(self) -> None:
        game = GameState(create_demo_map())
        tower = game.build("gun_tower", Position(30, 6))
        tower.take_damage(4)
        game.recalculate_power()

        self.assertEqual(tower.health_efficiency, 0.6)
        self.assertAlmostEqual(tower.efficiency, 0.6)
        self.assertAlmostEqual(tower.current_damage(), 4.0 * 0.6)
        self.assertAlmostEqual(tower.attack_speed_multiplier(), 0.6)

        tower.reset_cooldown()

        self.assertAlmostEqual(tower.cooldown_remaining, 1.0 / 0.6)

    def test_snapshot_exposes_condition_efficiency_separately(self) -> None:
        game = GameState(create_demo_map())
        tower = game.build("gun_tower", Position(30, 6))
        tower.take_damage(4)
        game.recalculate_power()

        snapshot = game.snapshot()
        building = game.cell_snapshot(Position(30, 6)).building

        self.assertEqual(snapshot.status.power.efficiency, 1.0)
        self.assertIsNotNone(building)
        assert building is not None
        self.assertEqual(building.health_efficiency, 0.6)
        self.assertAlmostEqual(building.efficiency, 0.6)


if __name__ == "__main__":
    unittest.main()
