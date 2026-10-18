"""Regression coverage for power-node health and saboteur attacks."""

import unittest

from grid_td.enemies import create_enemy
from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


class GridDamageTest(unittest.TestCase):
    """Verify that saboteurs can damage and disable power nodes."""

    def setUp(self) -> None:
        self.game = GameState(create_demo_map())

    def _place_saboteur(self, path_progress: float = 30.0):
        """Place a saboteur at a deterministic point on the demo route."""
        self.game.start_next_wave()
        saboteur = create_enemy("saboteur")
        saboteur.path_progress = path_progress
        self.game.enemies = [saboteur]
        return saboteur

    def test_power_node_has_mutable_health(self) -> None:
        node = self.game.build("power_node", Position(30, 9))

        self.assertEqual(node.hp, node.max_hp)
        node.take_damage(2)

        self.assertEqual(node.hp, node.max_hp - 2)
        self.assertFalse(node.is_destroyed)

        node.take_damage(node.hp)
        self.assertEqual(node.hp, 0)
        self.assertTrue(node.is_destroyed)

    def test_saboteur_attacks_node_in_range_and_respects_cooldown(self) -> None:
        node = self.game.build("power_node", Position(30, 9))
        saboteur = self._place_saboteur()
        saboteur.speed = 0.0

        self.game.step(1.0)
        self.assertEqual(node.hp, node.max_hp - saboteur.attack_damage)
        self.assertEqual(saboteur.attack_cooldown_remaining, 1.0)

        self.game.step(0.5)
        self.assertEqual(node.hp, node.max_hp - saboteur.attack_damage)

        self.game.step(0.5)
        self.assertEqual(node.hp, node.max_hp - 2 * saboteur.attack_damage)

    def test_saboteur_out_of_range_does_not_damage_node(self) -> None:
        node = self.game.build("power_node", Position(30, 15))
        self._place_saboteur(path_progress=0.0)

        self.game.step(1.0)

        self.assertEqual(node.hp, node.max_hp)

    def test_only_saboteurs_attack_power_nodes(self) -> None:
        node = self.game.build("power_node", Position(30, 9))
        self.game.start_next_wave()
        enemy = create_enemy("basic")
        enemy.path_progress = 30.0
        self.game.enemies = [enemy]

        self.game.step(1.0)

        self.assertEqual(node.hp, node.max_hp)

    def test_destroyed_node_stops_transmitting_power(self) -> None:
        node = self.game.build("power_node", Position(30, 9))
        tower = self.game.build("gun_tower", Position(30, 12))
        tower.cooldown_remaining = 999.0
        node.take_damage(node.hp - 1)
        self._place_saboteur()

        self.assertTrue(tower.connected_to_grid)
        self.game.step(1.0)

        self.assertEqual(node.hp, 0)
        self.assertTrue(node.is_destroyed)
        self.assertFalse(node.connected_to_grid)
        self.assertFalse(tower.connected_to_grid)
        self.assertEqual(tower.efficiency, 0.0)


if __name__ == "__main__":
    unittest.main()
