"""Manual tower targeting must be a validated public command.

These tests protect the GUI-facing `set_tower_target()` and
`clear_tower_target()` commands: their rejection rules, the override of
automatic selection, and the fallback from a stale manual target.
"""

import unittest
from collections.abc import Callable

from grid_td.enemies import Enemy, create_enemy
from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


class TowerTargetingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game = GameState(create_demo_map())
        # On the map's turn, the tower at (27, 0) is within range of the route
        # end and connected to the core without extra power infrastructure.
        self.tower = self.game.build("gun_tower", Position(27, 0))

    def _spawn(self, enemy_id: int, path_progress: float) -> Enemy:
        enemy = create_enemy("basic")
        enemy.id = enemy_id
        enemy.path_progress = path_progress
        return enemy

    def _enter_night_with(self, enemies: list[Enemy]) -> None:
        self.game.start_next_wave()
        # Drop the runner so step(0) does not spawn the demo wave's first enemy.
        self.game.wave_runner = None
        self.game.enemies = list(enemies)

    def assert_rejected_without_changes(self, operation: Callable[[], object]) -> None:
        before = self.game.snapshot()
        target_before = self.tower.target_enemy_id
        with self.assertRaises(ValueError):
            operation()
        self.assertEqual(self.game.snapshot(), before)
        self.assertEqual(self.tower.target_enemy_id, target_before)

    def test_set_tower_target_records_a_living_enemy(self) -> None:
        enemy = self._spawn(5, 0.0)
        self.game.enemies.append(enemy)

        self.game.set_tower_target(self.tower.id, enemy.id)

        self.assertEqual(self.tower.target_enemy_id, enemy.id)
        self.assertEqual(
            self.game.cell_snapshot(self.tower.position).building.target_enemy_id,
            enemy.id,
        )

    def test_set_tower_target_rejects_invalid_arguments(self) -> None:
        enemy = self._spawn(5, 0.0)
        self.game.enemies.append(enemy)
        node = self.game.build("power_node", Position(30, 9))
        core_id = self.game.cell_snapshot(Position(30, 3)).building.id

        for tower_id in (0, -1, True, False, 1.0, "1", None, 999, core_id, node.id):
            with self.subTest(tower_id=tower_id):
                self.assert_rejected_without_changes(
                    lambda: self.game.set_tower_target(tower_id, enemy.id)
                )
        for enemy_id in (0, -1, True, False, 1.0, "1", None, 999):
            with self.subTest(enemy_id=enemy_id):
                self.assert_rejected_without_changes(
                    lambda: self.game.set_tower_target(self.tower.id, enemy_id)
                )

    def test_set_tower_target_rejects_dead_enemy(self) -> None:
        enemy = self._spawn(5, 0.0)
        enemy.hp = 0
        self.game.enemies.append(enemy)

        self.assert_rejected_without_changes(
            lambda: self.game.set_tower_target(self.tower.id, enemy.id)
        )

    def test_manual_target_overrides_automatic_selection(self) -> None:
        leader = self._spawn(1, 35.0)  # Automatic selection prefers this one.
        follower = self._spawn(2, 34.0)
        self._enter_night_with([leader, follower])
        self.game.set_tower_target(self.tower.id, follower.id)

        self.game.step(0.0)

        self.assertLess(follower.hp, leader.hp)
        self.assertEqual(leader.hp, leader.max_hp)

    def test_stale_manual_target_falls_back_to_automatic_selection(self) -> None:
        leader = self._spawn(1, 35.0)
        self._enter_night_with([leader])
        # Simulate a manual target that has since left the board.
        self.tower.target_enemy_id = 999

        self.game.step(0.0)

        self.assertIsNone(self.tower.target_enemy_id)
        self.assertLess(leader.hp, leader.max_hp)

    def test_clear_tower_target_restores_automatic_selection(self) -> None:
        enemy = self._spawn(5, 35.0)
        self.game.enemies.append(enemy)
        self.game.set_tower_target(self.tower.id, enemy.id)

        self.game.clear_tower_target(self.tower.id)

        self.assertIsNone(self.tower.target_enemy_id)

    def test_targeting_rejects_ended_game_or_destroyed_core(self) -> None:
        enemy = self._spawn(5, 0.0)
        self.game.enemies.append(enemy)
        self.game.result_message = "Defeat. The core was destroyed."
        self.assert_rejected_without_changes(
            lambda: self.game.set_tower_target(self.tower.id, enemy.id)
        )
        self.assert_rejected_without_changes(
            lambda: self.game.clear_tower_target(self.tower.id)
        )

        self.game.result_message = ""
        self.game.core_hp = 0
        self.assert_rejected_without_changes(
            lambda: self.game.set_tower_target(self.tower.id, enemy.id)
        )


if __name__ == "__main__":
    unittest.main()
