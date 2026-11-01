"""Coverage for conservative attacks on ordinary buildings."""

import unittest

from grid_td.enemies import create_enemy
from grid_td.game_state import GameState
from grid_td.map import GridMap
from grid_td.path import RoutePath
from grid_td.position import Position, WorldPosition


def make_game() -> GameState:
    grid_map = GridMap(
        width=12,
        height=12,
        route=(Position(0, 0),),
        core_position=Position(9, 9),
        mine_positions=frozenset(),
        high_ground_positions=frozenset(),
        illegal_ground_positions=frozenset(),
    )
    game = GameState(grid_map, gold=1000)
    game.start_next_wave()
    game.wave_runner = None
    return game


def place_enemy(game: GameState, kind: str = "basic"):
    enemy = create_enemy(kind)
    enemy.id = 99
    # Path planning requires a positive speed; this keeps movement negligible
    # while allowing attack and cooldown behavior to be isolated.
    enemy.speed = 0.01
    enemy.route = RoutePath(
        (WorldPosition(4.5, 4.5), WorldPosition(4.5, 5.5))
    )
    game.enemies = [enemy]
    return enemy


class EnemyBuildingAttackTest(unittest.TestCase):
    def test_basic_enemy_attacks_a_tower_and_exposes_target(self) -> None:
        game = make_game()
        tower = game.build("gun_tower", Position(3, 3))
        enemy = place_enemy(game)

        game.step(0.0)

        self.assertEqual(tower.hp, tower.max_hp - 1)
        self.assertEqual(enemy.target_building_id, tower.id)
        enemy_snapshot = game.cell_snapshot(Position(4, 4)).enemies[0]
        self.assertEqual(enemy_snapshot.target_building_id, tower.id)

    def test_attack_cooldown_limits_repeated_hits(self) -> None:
        game = make_game()
        tower = game.build("gun_tower", Position(3, 3))
        place_enemy(game)

        game.step(0.0)
        self.assertEqual(tower.hp, tower.max_hp - 1)
        game.step(5.0)
        self.assertEqual(tower.hp, tower.max_hp - 1)
        game.step(1.0)
        self.assertEqual(tower.hp, tower.max_hp - 2)

    def test_destroying_target_replans_and_clears_normal_enemy_target(self) -> None:
        game = make_game()
        tower = game.build("gun_tower", Position(3, 3))
        tower.current_hp = 1
        enemy = place_enemy(game)

        game.step(0.0)

        self.assertTrue(tower.is_destroyed)
        self.assertIsNone(enemy.target_building_id)
        self.assertFalse(enemy.stalled)

    def test_normal_enemy_does_not_attack_power_buildings(self) -> None:
        game = make_game()
        plant = game.build("power_plant", Position(3, 3))
        place_enemy(game)

        game.step(0.0)

        self.assertEqual(plant.hp, plant.max_hp)

    def test_nearest_ordinary_building_wins_and_saboteur_keeps_power_priority(self) -> None:
        game = make_game()
        near = game.build("gun_tower", Position(3, 3))
        far = game.build("cannon_tower", Position(6, 3))
        enemy = place_enemy(game)

        game.step(0.0)
        self.assertEqual(enemy.target_building_id, near.id)
        self.assertEqual(near.hp, near.max_hp - 1)
        self.assertEqual(far.hp, far.max_hp)

        saboteur = place_enemy(game, "saboteur")
        plant = game.build("power_plant", Position(3, 6))
        saboteur.route = RoutePath(
            (WorldPosition(4.5, 7.5), WorldPosition(4.5, 8.5))
        )
        game.step(0.0)
        self.assertEqual(saboteur.target_building_id, plant.id)


if __name__ == "__main__":
    unittest.main()
