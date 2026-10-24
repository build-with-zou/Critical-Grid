"""Combat rules that apply to enemy damage and cannon attacks."""

import unittest

from grid_td.enemies import Enemy, create_enemy
from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


class ArmorTest(unittest.TestCase):
    def test_armored_enemy_takes_reduced_damage(self) -> None:
        armored = create_enemy("armored")
        basic = create_enemy("basic")

        armored.take_damage(4.0)
        basic.take_damage(4.0)

        self.assertEqual(armored.damage_reduction, 0.25)
        self.assertAlmostEqual(armored.hp, armored.max_hp - 3.0)
        self.assertAlmostEqual(basic.hp, basic.max_hp - 4.0)

    def test_tower_damage_respects_armor(self) -> None:
        game = GameState(create_demo_map())
        game.build("gun_tower", Position(30, 6))
        game.start_next_wave()
        game.wave_runner = None
        armored = create_enemy("armored")
        armored.path_progress = 30.0
        game.enemies = [armored]

        game.step(0.0)

        self.assertAlmostEqual(armored.hp, armored.max_hp - 3.0)

    def test_invalid_damage_reduction_is_rejected(self) -> None:
        for value in (-0.1, 1.1, True, "0.25", float("nan"), 10**1000):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Enemy(
                    "Invalid",
                    max_hp=1,
                    speed=0,
                    damage_to_core=1,
                    reward=0,
                    damage_reduction=value,
                )


if __name__ == "__main__":
    unittest.main()
