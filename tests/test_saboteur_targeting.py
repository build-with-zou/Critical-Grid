"""Saboteur infrastructure targeting and opportunistic retargeting."""

import unittest

from grid_td.enemies import create_enemy
from grid_td.game_state import GameState
from grid_td.map import GridMap
from grid_td.path import RoutePath
from grid_td.position import Position, WorldPosition


def make_map() -> GridMap:
    return GridMap(
        width=30,
        height=20,
        route=(Position(0, 0),),
        core_position=Position(0, 0),
        mine_positions=frozenset(),
        high_ground_positions=frozenset(),
        illegal_ground_positions=frozenset(),
    )


def place_saboteur(game: GameState, position: Position = Position(0, 6)):
    enemy = create_enemy("saboteur")
    enemy.id = 999
    enemy.route = RoutePath((WorldPosition(position.x + 0.5, position.y + 0.5),))
    game.enemies = [enemy]
    return enemy


class SaboteurTargetSelectionTest(unittest.TestCase):
    def test_plant_target_wins_over_closer_node(self) -> None:
        game = GameState(make_map(), gold=1000)
        plant = game.build("power_plant", Position(18, 0))
        game.build("power_node", Position(3, 6))
        saboteur = place_saboteur(game)

        game._assign_enemy_path(saboteur)

        self.assertEqual(saboteur.target_building_id, plant.id)
        self.assertIsNone(saboteur.breach_target_id)

    def test_nearest_node_is_used_without_a_plant(self) -> None:
        game = GameState(make_map(), gold=1000)
        node = game.build("power_node", Position(3, 6))
        saboteur = place_saboteur(game)

        game._assign_enemy_path(saboteur)

        self.assertEqual(saboteur.target_building_id, node.id)

    def test_no_power_buildings_falls_back_to_core(self) -> None:
        game = GameState(make_map(), gold=1000)
        saboteur = place_saboteur(game)

        game._assign_enemy_path(saboteur)

        self.assertIsNone(saboteur.target_building_id)
        self.assertFalse(saboteur.stalled)
        self.assertTrue(saboteur.route.points)

    def test_normal_enemy_does_not_take_power_target(self) -> None:
        game = GameState(make_map(), gold=1000)
        game.build("power_plant", Position(18, 0))
        enemy = create_enemy("basic")
        enemy.id = 999
        enemy.route = RoutePath((WorldPosition(0.5, 6.5),))
        game.enemies = [enemy]

        game._assign_enemy_path(enemy)

        self.assertIsNone(enemy.target_building_id)


class SaboteurOpportunisticTargetTest(unittest.TestCase):
    def test_switch_from_out_of_range_plant_to_in_range_node(self) -> None:
        game = GameState(make_map(), gold=1000)
        plant = game.build("power_plant", Position(18, 0))
        node = game.build("power_node", Position(3, 6))
        saboteur = place_saboteur(game)
        game._assign_enemy_path(saboteur)
        self.assertEqual(saboteur.target_building_id, plant.id)

        game._refresh_saboteur_targets()

        self.assertEqual(saboteur.target_building_id, node.id)
        self.assertEqual(saboteur.route.length, 0)

    def test_switch_from_node_to_higher_priority_plant(self) -> None:
        game = GameState(make_map(), gold=1000)
        node = game.build("power_node", Position(3, 6))
        plant = game.build("power_plant", Position(3, 3))
        saboteur = place_saboteur(game)
        saboteur.target_building_id = node.id
        saboteur.route = RoutePath((WorldPosition(0.5, 6.5),))

        game._refresh_saboteur_targets()

        self.assertEqual(saboteur.target_building_id, plant.id)

    def test_same_priority_target_is_not_thrashed(self) -> None:
        game = GameState(make_map(), gold=1000)
        first = game.build("power_node", Position(3, 6))
        game.build("power_node", Position(3, 3))
        saboteur = place_saboteur(game)
        saboteur.target_building_id = first.id
        saboteur.route = RoutePath((WorldPosition(0.5, 6.5),))

        game._refresh_saboteur_targets()

        self.assertEqual(saboteur.target_building_id, first.id)

    def test_target_is_attacked_after_switch(self) -> None:
        game = GameState(make_map(), gold=1000)
        game.build("power_plant", Position(18, 0))
        node = game.build("power_node", Position(3, 6))
        saboteur = place_saboteur(game)
        game._assign_enemy_path(saboteur)
        game.start_next_wave()
        game.wave_runner = None

        game.step(0.25)

        self.assertEqual(saboteur.target_building_id, node.id)
        self.assertEqual(node.hp, node.max_hp - 1)


class SaboteurRetargetAndSnapshotTest(unittest.TestCase):
    def test_destroyed_plant_retargets_to_node(self) -> None:
        game = GameState(make_map(), gold=1000)
        plant = game.build("power_plant", Position(3, 6))
        node = game.build("power_node", Position(3, 12))
        saboteur = place_saboteur(game)
        game._assign_enemy_path(saboteur)
        self.assertEqual(saboteur.target_building_id, plant.id)
        plant.take_damage(plant.hp)

        game._replan_all_enemies()

        self.assertEqual(saboteur.target_building_id, node.id)

    def test_target_is_exposed_in_snapshot(self) -> None:
        game = GameState(make_map(), gold=1000)
        plant = game.build("power_plant", Position(18, 0))
        saboteur = place_saboteur(game)
        game._assign_enemy_path(saboteur)

        position = saboteur.position_on_route(saboteur.route)
        snapshot = game.cell_snapshot(position)

        self.assertEqual(snapshot.enemies[0].target_building_id, plant.id)


if __name__ == "__main__":
    unittest.main()
