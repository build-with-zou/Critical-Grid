"""Fixed-step simulation consistency and boundary coverage."""

import unittest

from grid_td.enemies import create_enemy
from grid_td.game_state import GameEventType, GamePhase, GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


def make_duel_game(enemy_hp: float = 10.0):
    """Return a connected tower and one stationary enemy in NIGHT."""
    game = GameState(create_demo_map())
    tower = game.build("gun_tower", Position(30, 6))
    game.start_next_wave()
    game.wave_runner = None
    enemy = create_enemy("basic")
    enemy.id = 1
    enemy.path_progress = 30.0
    enemy.speed = 0.0
    enemy.max_hp = enemy_hp
    enemy.hp = enemy_hp
    game.enemies = [enemy]
    return game, tower, enemy


class FixedStepTest(unittest.TestCase):
    def test_large_step_matches_many_small_steps(self) -> None:
        large, large_tower, large_enemy = make_duel_game()
        small, small_tower, small_enemy = make_duel_game()

        large.step(3.0)
        small_events = []
        for _ in range(60):
            small.step(0.05)
            small_events.extend(small.events)

        self.assertAlmostEqual(large.elapsed_seconds, 3.0)
        self.assertAlmostEqual(small.elapsed_seconds, 3.0)
        self.assertEqual(large_enemy.hp, small_enemy.hp)
        self.assertEqual(large_enemy.path_progress, small_enemy.path_progress)
        self.assertAlmostEqual(
            large_tower.cooldown_remaining, small_tower.cooldown_remaining
        )
        self.assertEqual(large.gold, small.gold)
        self.assertEqual(large.enemies, small.enemies)
        self.assertEqual(
            sum(event.type is GameEventType.TOWER_ATTACK for event in large.events),
            sum(event.type is GameEventType.TOWER_ATTACK for event in small_events),
        )

    def test_large_step_preserves_repeated_attacks(self) -> None:
        game, _, enemy = make_duel_game(enemy_hp=1000.0)

        game.step(6.0)

        attacks = [
            event for event in game.events
            if event.type is GameEventType.TOWER_ATTACK
        ]
        self.assertEqual(len(attacks), 6)
        self.assertEqual(
            sum(
                event.type is GameEventType.ENEMY_DAMAGED
                for event in game.events
            ),
            6,
        )
        self.assertLess(enemy.hp, enemy.max_hp)

    def test_non_multiple_duration_advances_exact_remainder(self) -> None:
        game = GameState(create_demo_map())
        game.start_next_wave()
        game.wave_runner = None

        game.step(0.07)

        self.assertAlmostEqual(game.elapsed_seconds, 0.07)

    def test_zero_duration_still_processes_time_zero_events_once(self) -> None:
        game = GameState(create_demo_map())
        game.start_next_wave()

        game.step(0.0)

        self.assertEqual(len(game.enemies), 1)
        self.assertEqual(game.elapsed_seconds, 0.0)
        self.assertEqual(
            [event.type for event in game.events],
            [GameEventType.ENEMY_SPAWNED],
        )

    def test_invalid_duration_preserves_events_and_state(self) -> None:
        game = GameState(create_demo_map())
        game.start_next_wave()
        game.step(0.0)
        before = game.snapshot()
        events_before = game.events

        with self.assertRaises(ValueError):
            game.step(-0.05)

        self.assertEqual(game.snapshot(), before)
        self.assertEqual(game.events, events_before)
        self.assertEqual(game.phase, GamePhase.NIGHT)


if __name__ == "__main__":
    unittest.main()
