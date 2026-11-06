"""Tests for wave base rewards and settlement payouts."""

from __future__ import annotations

import unittest

from grid_td.game_state import GamePhase, GameState
from grid_td.map import create_demo_map
from grid_td.waves import SpawnGroup, Wave


class WaveRewardTest(unittest.TestCase):
    def test_wave_reward_defaults_to_zero(self) -> None:
        self.assertEqual(Wave("No Reward", "", ()).reward, 0)

    def test_invalid_wave_rewards_are_rejected(self) -> None:
        for reward in (-1, True, 1.5, "10"):
            with self.subTest(reward=reward), self.assertRaisesRegex(
                ValueError, "reward"
            ):
                Wave("Bad Reward", "", (), reward=reward)

    def test_end_wave_pays_reward_once(self) -> None:
        game = GameState(create_demo_map(), core_hp=100)
        game.waves = (
            Wave(
                "Reward Wave",
                "",
                (SpawnGroup("basic", 1, 1.0),),
                reward=25,
            ),
        )
        game.start_next_wave()
        for _ in range(40):
            game.step(1.0)
            if game.waiting_for_next_wave:
                break

        self.assertTrue(game.waiting_for_next_wave)
        gold_before = game.gold
        message = game.end_wave()

        self.assertEqual(game.gold, gold_before + 25)
        self.assertIn("Reward +25", message)
        self.assertEqual(game.phase, GamePhase.VICTORY)

    def test_final_wave_reward_is_paid_at_victory(self) -> None:
        game = GameState(create_demo_map(), core_hp=100)
        game.waves = (
            Wave(
                "Final Reward",
                "",
                (SpawnGroup("basic", 1, 1.0),),
                reward=40,
            ),
        )
        game.start_next_wave()
        for _ in range(40):
            game.step(1.0)
            if game.waiting_for_next_wave:
                break

        gold_before = game.gold
        game.end_wave()

        self.assertEqual(game.phase, GamePhase.VICTORY)
        self.assertEqual(game.gold, gold_before + 40)


if __name__ == "__main__":
    unittest.main()
