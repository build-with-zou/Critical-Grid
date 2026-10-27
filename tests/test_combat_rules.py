"""Combat rules that apply to enemy damage and cannon attacks."""

import unittest

from grid_td.enemies import Enemy, create_enemy
from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


class ArmorTest(unittest.TestCase):
    def test_armored_enemy_subtracts_flat_armor(self) -> None:
        armored = create_enemy("armored")
        basic = create_enemy("basic")

        armored.take_damage(4.0)
        basic.take_damage(4.0)

        self.assertEqual(armored.armor, 2)
        self.assertAlmostEqual(armored.hp, armored.max_hp - 2.0)
        self.assertAlmostEqual(basic.hp, basic.max_hp - 4.0)

    def test_positive_hit_deals_at_least_one_damage(self) -> None:
        armored = create_enemy("armored")

        armored.take_damage(1.0)

        self.assertAlmostEqual(armored.hp, armored.max_hp - 1.0)

    def test_non_positive_hit_does_not_damage(self) -> None:
        armored = create_enemy("armored")

        armored.take_damage(0.0)
        armored.take_damage(-5.0)

        self.assertEqual(armored.hp, armored.max_hp)

    def test_tower_damage_respects_armor(self) -> None:
        game = GameState(create_demo_map())
        game.build("gun_tower", Position(30, 6))
        game.start_next_wave()
        game.wave_runner = None
        armored = create_enemy("armored")
        armored.path_progress = 30.0
        game.enemies = [armored]

        game.step(0.0)

        self.assertAlmostEqual(armored.hp, armored.max_hp - 2.0)

    def test_slow_tower_applies_minimum_damage_and_slow(self) -> None:
        game = GameState(create_demo_map())
        game.build("slow_tower", Position(30, 6))
        game.start_next_wave()
        game.wave_runner = None
        armored = create_enemy("armored")
        armored.path_progress = 30.0
        game.enemies = [armored]

        game.step(0.0)

        self.assertAlmostEqual(armored.hp, armored.max_hp - 1.0)
        self.assertTrue(armored.is_slowed)

    def test_snapshot_exposes_enemy_armor(self) -> None:
        game = GameState(create_demo_map())
        armored = create_enemy("armored")
        game.enemies = [armored]

        cell = game.cell_snapshot(armored.position_on_route(game.grid_map.path))

        self.assertEqual(cell.enemies[0].armor, 2)

    def test_invalid_armor_is_rejected(self) -> None:
        for value in (-1, True, 1.5, "2", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Enemy(
                    "Invalid",
                    max_hp=1,
                    speed=0,
                    damage_to_core=1,
                    reward=0,
                    armor=value,
                )


class CannonSplashTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game = GameState(create_demo_map())
        self.tower = self.game.build("cannon_tower", Position(30, 6))
        self.game.start_next_wave()
        self.game.wave_runner = None

    def _enemy(self, path_progress: float, kind: str = "basic") -> Enemy:
        enemy = create_enemy(kind)
        enemy.path_progress = path_progress
        return enemy

    def _run_attack(self, *enemies: Enemy) -> None:
        self.game.enemies = list(enemies)
        self.game.step(0.0)

    def test_splash_hits_other_enemies_around_primary_target(self) -> None:
        primary = self._enemy(34.0)
        neighbor = self._enemy(31.0)
        far = self._enemy(20.0)

        self._run_attack(primary, neighbor, far)

        self.assertAlmostEqual(primary.hp, primary.max_hp - 8.0)
        self.assertAlmostEqual(neighbor.hp, neighbor.max_hp - 4.0)
        self.assertEqual(far.hp, far.max_hp)

    def test_splash_boundary_is_inclusive_and_outside_is_ignored(self) -> None:
        primary = self._enemy(34.0)
        boundary = self._enemy(31.0)
        outside = self._enemy(30.9)

        self._run_attack(primary, boundary, outside)

        self.assertAlmostEqual(boundary.hp, boundary.max_hp - 4.0)
        self.assertEqual(outside.hp, outside.max_hp)

    def test_primary_target_is_not_hit_twice(self) -> None:
        primary = self._enemy(34.0)

        self._run_attack(primary)

        self.assertAlmostEqual(primary.hp, primary.max_hp - 8.0)

    def test_splash_still_resolves_when_primary_target_dies(self) -> None:
        primary = Enemy(
            "Fragile",
            max_hp=1,
            speed=0,
            damage_to_core=0,
            reward=0,
            path_progress=34.0,
        )
        neighbor = self._enemy(31.0)

        self._run_attack(primary, neighbor)

        self.assertFalse(primary.is_alive)
        self.assertAlmostEqual(neighbor.hp, neighbor.max_hp - 4.0)

    def test_splash_is_reduced_by_armor(self) -> None:
        primary = self._enemy(34.0)
        armored = self._enemy(31.0, kind="armored")

        self._run_attack(primary, armored)

        self.assertAlmostEqual(armored.hp, armored.max_hp - 2.0)

    def test_non_cannon_towers_do_not_splash(self) -> None:
        game = GameState(create_demo_map())
        game.build("gun_tower", Position(30, 6))
        game.start_next_wave()
        game.wave_runner = None
        primary = self._enemy(34.0)
        neighbor = self._enemy(31.0)

        game.enemies = [primary, neighbor]
        game.step(0.0)

        self.assertAlmostEqual(primary.hp, primary.max_hp - 4.0)
        self.assertEqual(neighbor.hp, neighbor.max_hp)


if __name__ == "__main__":
    unittest.main()

