"""Snapshot fields used by presentation for combat and power details."""

import unittest

from grid_td.enemies import create_enemy
from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


class BuildingSnapshotContractTest(unittest.TestCase):
    def test_cannon_exposes_splash_parameters(self) -> None:
        game = GameState(create_demo_map())
        game.build("cannon_tower", Position(30, 6))

        building = game.cell_snapshot(Position(30, 6)).building

        self.assertIsNotNone(building)
        assert building is not None
        self.assertEqual(building.splash_radius, 3.0)
        self.assertEqual(building.splash_damage_ratio, 0.5)

    def test_non_cannon_building_has_no_splash_parameters(self) -> None:
        game = GameState(create_demo_map())
        game.build("gun_tower", Position(30, 6))

        building = game.cell_snapshot(Position(30, 6)).building

        self.assertIsNotNone(building)
        assert building is not None
        self.assertIsNone(building.splash_radius)
        self.assertIsNone(building.splash_damage_ratio)

    def test_damaged_plant_exposes_effective_power_supply(self) -> None:
        game = GameState(create_demo_map())
        plant = game.build("power_plant", Position(30, 6))
        plant.take_damage(2)
        game.recalculate_power()

        building = game.cell_snapshot(Position(30, 6)).building

        self.assertIsNotNone(building)
        assert building is not None
        self.assertEqual(building.power_supply, 10)
        self.assertEqual(building.effective_power_supply, 9)


class EnemySnapshotContractTest(unittest.TestCase):
    def test_saboteur_exposes_attack_details(self) -> None:
        game = GameState(create_demo_map())
        saboteur = create_enemy("saboteur")
        saboteur.id = 7
        saboteur.path_progress = 30.0
        game.enemies = [saboteur]

        cell = game.cell_snapshot(saboteur.position_on_route(game.grid_map.path))
        enemy = cell.enemies[0]

        self.assertEqual(enemy.attack_range, 6.0)
        self.assertEqual(enemy.attack_damage, 1)
        self.assertEqual(enemy.armor, 0)

    def test_non_saboteur_has_zero_attack_details(self) -> None:
        game = GameState(create_demo_map())
        basic = create_enemy("basic")
        basic.path_progress = 30.0
        game.enemies = [basic]

        cell = game.cell_snapshot(basic.position_on_route(game.grid_map.path))
        enemy = cell.enemies[0]

        self.assertEqual(enemy.attack_range, 0.0)
        self.assertEqual(enemy.attack_damage, 0)


if __name__ == "__main__":
    unittest.main()
