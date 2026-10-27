"""Integration coverage for per-enemy paths, replanning and breach attacks."""

import unittest

from grid_td.enemies import create_enemy
from grid_td.game_state import GameState
from grid_td.map import GridMap, create_demo_map
from grid_td.path import RoutePath
from grid_td.position import Position, WorldPosition


def make_map(
    width: int,
    height: int,
    core_position: Position,
    *,
    route: tuple[Position, ...] = (Position(0, 0),),
) -> GridMap:
    """Build a minimal open-ground map for path integration tests."""
    return GridMap(
        width=width,
        height=height,
        route=route,
        core_position=core_position,
        mine_positions=frozenset(),
        high_ground_positions=frozenset(),
        illegal_ground_positions=frozenset(),
    )


def make_game_with_wall() -> tuple[GameState, object, list]:
    """Create a wall game plus a manually placed enemy at the entrance."""
    grid_map = make_map(12, 12, Position(9, 7))
    game = GameState(grid_map, gold=1000)
    buildings = [
        game.build("gun_tower", Position(3, y))
        for y in (0, 3, 6, 9)
    ]
    enemy = create_enemy("basic")
    enemy.id = 999
    game.enemies = [enemy]
    game.start_next_wave()
    game.wave_runner = None
    game._assign_enemy_path(enemy)
    return game, enemy, buildings


class SpawnPathTest(unittest.TestCase):
    def test_spawned_enemy_receives_a_path_snapshot(self) -> None:
        game = GameState(create_demo_map())
        game.start_next_wave()
        game.step(0.0)

        enemy = game.enemies[0]
        self.assertIsNotNone(enemy.route)
        snapshot = game.cell_snapshot(enemy.position_on_route(enemy.active_path(game.grid_map.path)))
        enemy_snapshot = snapshot.enemies[0]

        self.assertGreater(len(enemy_snapshot.path), 0)
        self.assertEqual(enemy_snapshot.path, enemy.route.points)
        self.assertIsNone(enemy_snapshot.breach_target_id)


class ReplanAndBreachTest(unittest.TestCase):
    def test_building_a_wall_creates_a_breach_target(self) -> None:
        grid_map = make_map(12, 12, Position(9, 7))
        game = GameState(grid_map, gold=1000)
        enemy = create_enemy("basic")
        enemy.id = 999
        game.enemies = [enemy]
        game.start_next_wave()
        game.wave_runner = None
        game._assign_enemy_path(enemy)
        self.assertIsNone(enemy.breach_target_id)

        wall = [
            game.build("gun_tower", Position(3, y))
            for y in (0, 3, 6, 9)
        ]

        self.assertIsNotNone(enemy.breach_target_id)
        self.assertIn(enemy.breach_target_id, {building.id for building in wall})
        self.assertTrue(enemy.route.points)

    def test_selling_a_wall_piece_restores_a_normal_path(self) -> None:
        game, enemy, buildings = make_game_with_wall()
        self.assertIsNotNone(enemy.breach_target_id)

        game.sell_building(buildings[1].id)

        self.assertIsNone(enemy.breach_target_id)
        self.assertFalse(enemy.stalled)

    def test_breach_attack_damages_the_target_building(self) -> None:
        game, enemy, buildings = make_game_with_wall()
        target_id = enemy.breach_target_id
        target = next(building for building in buildings if building.id == target_id)
        before = target.hp

        for _ in range(120):
            game.step(0.05)

        self.assertLess(target.hp, before)

    def test_snapshot_exposes_breach_target(self) -> None:
        game, enemy, _ = make_game_with_wall()
        position = enemy.position_on_route(enemy.route)

        snapshot = game.cell_snapshot(position)
        enemy_snapshot = snapshot.enemies[0]

        self.assertEqual(enemy_snapshot.breach_target_id, enemy.breach_target_id)
        self.assertEqual(enemy_snapshot.path, enemy.route.points)


class EnemyOccupancyTest(unittest.TestCase):
    def test_building_on_a_living_enemy_is_rejected(self) -> None:
        grid_map = make_map(
            12,
            12,
            Position(9, 7),
            route=(Position(6, 0),),
        )
        game = GameState(grid_map, gold=1000)
        enemy = create_enemy("basic")
        enemy.id = 999
        enemy.route = RoutePath((WorldPosition(0.5, 0.5),))
        game.enemies = [enemy]

        with self.assertRaisesRegex(ValueError, "enemy"):
            game.build("gun_tower", Position(0, 0))

    def test_repair_on_a_living_enemy_is_rejected(self) -> None:
        grid_map = make_map(
            12,
            12,
            Position(9, 7),
            route=(Position(6, 0),),
        )
        game = GameState(grid_map, gold=1000)
        building = game.build("gun_tower", Position(3, 3))
        building.take_damage(1)
        enemy = create_enemy("basic")
        enemy.id = 999
        enemy.route = RoutePath((WorldPosition(4.5, 4.5),))
        game.enemies = [enemy]

        with self.assertRaisesRegex(ValueError, "enemy"):
            game.repair_building(building.id)


if __name__ == "__main__":
    unittest.main()
