"""Structured simulation event coverage."""

import unittest
from dataclasses import FrozenInstanceError

from grid_td.enemies import create_enemy
from grid_td.game_state import GameEventType, GameState
from grid_td.map import GridMap, create_demo_map
from grid_td.path import RoutePath
from grid_td.position import Position, WorldPosition


def make_isolated_game() -> GameState:
    """Create a small NIGHT game with no wave runner for direct fixtures."""
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


def place_enemy(
    game: GameState,
    kind: str = "basic",
    enemy_id: int = 99,
    path_progress: float = 0.0,
):
    enemy = create_enemy(kind)
    enemy.id = enemy_id
    enemy.speed = 0.01
    enemy.path_progress = path_progress
    enemy.route = RoutePath(
        (WorldPosition(4.5, 4.5), WorldPosition(4.5, 5.5))
    )
    game.enemies = [enemy]
    return enemy


class EventTest(unittest.TestCase):
    def test_events_are_immutable_and_match_snapshot(self) -> None:
        game = GameState(create_demo_map())
        game.start_next_wave()
        game.step(0.0)

        self.assertEqual(game.events, game.snapshot().events)
        spawn = next(
            event for event in game.events
            if event.type is GameEventType.ENEMY_SPAWNED
        )
        self.assertEqual(spawn.target_id, game.enemies[0].id)
        with self.assertRaises(FrozenInstanceError):
            spawn.amount = 1

    def test_tower_attack_damage_and_defeat_events(self) -> None:
        game = GameState(create_demo_map())
        tower = game.build("gun_tower", Position(30, 6))
        game.start_next_wave()
        game.wave_runner = None
        enemy = create_enemy("basic")
        enemy.id = 99
        enemy.speed = 0.0
        enemy.path_progress = 30.0
        enemy.hp = 1.0
        game.enemies = [enemy]

        game.step(0.0)

        types = [event.type for event in game.events]
        self.assertIn(GameEventType.TOWER_ATTACK, types)
        self.assertIn(GameEventType.ENEMY_DAMAGED, types)
        self.assertIn(GameEventType.ENEMY_DEFEATED, types)
        attack = next(
            event for event in game.events
            if event.type is GameEventType.TOWER_ATTACK
        )
        damaged = next(
            event for event in game.events
            if event.type is GameEventType.ENEMY_DAMAGED
        )
        defeated = next(
            event for event in game.events
            if event.type is GameEventType.ENEMY_DEFEATED
        )
        self.assertEqual(attack.source_id, tower.id)
        self.assertEqual(attack.target_id, enemy.id)
        self.assertEqual(damaged.source_id, tower.id)
        self.assertEqual(damaged.target_id, enemy.id)
        self.assertEqual(damaged.amount, 1.0)
        self.assertEqual(defeated.target_id, enemy.id)
        self.assertEqual(defeated.amount, enemy.reward)

    def test_cannon_splash_records_each_damaged_enemy(self) -> None:
        game = GameState(create_demo_map())
        tower = game.build("cannon_tower", Position(30, 6))
        game.start_next_wave()
        game.wave_runner = None

        lead = create_enemy("basic")
        lead.id = 1
        lead.path_progress = 34.0
        lead.speed = 0.0
        follower = create_enemy("basic")
        follower.id = 2
        follower.path_progress = 31.0
        follower.speed = 0.0
        game.enemies = [lead, follower]

        game.step(0.0)

        damaged = [
            event for event in game.events
            if event.type is GameEventType.ENEMY_DAMAGED
        ]
        self.assertEqual(
            {event.target_id for event in damaged},
            {lead.id, follower.id},
        )
        self.assertTrue(all(event.source_id == tower.id for event in damaged))

    def test_building_damaged_and_destroyed_events(self) -> None:
        game = make_isolated_game()
        tower = game.build("gun_tower", Position(3, 3))
        tower.current_hp = 1
        enemy = place_enemy(game)

        game.step(0.0)

        damaged = next(
            event for event in game.events
            if event.type is GameEventType.BUILDING_DAMAGED
        )
        destroyed = next(
            event for event in game.events
            if event.type is GameEventType.BUILDING_DESTROYED
        )
        self.assertEqual(damaged.source_id, enemy.id)
        self.assertEqual(damaged.target_id, tower.id)
        self.assertEqual(damaged.amount, 1)
        self.assertEqual(destroyed.source_id, enemy.id)
        self.assertEqual(destroyed.target_id, tower.id)

    def test_enemy_reached_core_and_core_damage_events(self) -> None:
        game = GameState(create_demo_map(), core_hp=10)
        game.start_next_wave()

        game.step(30.0)

        reached = [
            event for event in game.events
            if event.type is GameEventType.ENEMY_REACHED_CORE
        ]
        damaged = [
            event for event in game.events
            if event.type is GameEventType.CORE_DAMAGED
        ]
        self.assertTrue(reached)
        self.assertTrue(damaged)
        self.assertEqual(
            {event.target_id for event in reached},
            {event.source_id for event in damaged},
        )
        self.assertEqual(sum(event.amount for event in damaged), 5)
        self.assertEqual(game.core_hp, 5)

    def test_power_connection_changed_after_node_destruction(self) -> None:
        game = GameState(create_demo_map())
        node = game.build("power_node", Position(30, 9))
        tower = game.build("gun_tower", Position(30, 12))
        tower.cooldown_remaining = 999.0
        node.take_damage(node.hp - 1)
        saboteur = create_enemy("saboteur")
        saboteur.id = 50
        saboteur.path_progress = 30.0
        game.start_next_wave()
        game.enemies = [saboteur]

        game.step(0.0)

        self.assertEqual(node.hp, 0)
        self.assertFalse(tower.connected_to_grid)
        changed = [
            event for event in game.events
            if event.type is GameEventType.POWER_CONNECTION_CHANGED
        ]
        self.assertIn(
            (tower.id, False),
            {(event.target_id, event.connected) for event in changed},
        )

    def test_next_step_clears_events_and_invalid_step_preserves_them(self) -> None:
        game = make_isolated_game()
        game.build("gun_tower", Position(3, 3))
        place_enemy(game)
        game.step(0.0)
        events_before = game.events
        self.assertTrue(events_before)

        with self.assertRaises(ValueError):
            game.step(-1.0)
        self.assertEqual(game.events, events_before)

        game.enemies = []
        game.step(0.05)
        self.assertEqual(game.events, ())


if __name__ == "__main__":
    unittest.main()
