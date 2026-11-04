"""Tests for derived wave intelligence."""

from __future__ import annotations

import unittest
from dataclasses import replace

from grid_td.game_state import GameState
from grid_td.intel import build_wave_intel, preview_wave_intel
from grid_td.levels import load_demo_level
from grid_td.map import create_demo_map
from grid_td.position import Position
from grid_td.waves import SpawnGroup, Wave


class WaveIntelDerivationTest(unittest.TestCase):
    """Protect the preview/detailed projection and derived schedule fields."""

    def setUp(self) -> None:
        self.level = load_demo_level()

    def intel_for(self, index: int):
        wave = self.level.waves[index]
        return build_wave_intel(
            wave,
            index,
            self.level.grid_map.spawn_entrances,
            self.level.grid_map.path.points,
            self.level.grid_map.path.length,
        )

    def test_preview_hides_detailed_fields(self) -> None:
        intel = self.intel_for(0)
        preview = preview_wave_intel(intel)

        self.assertFalse(preview.is_detailed)
        self.assertEqual(preview.wave_index, 0)
        self.assertEqual(preview.wave_name, "Wave 1")
        self.assertEqual(preview.briefing, "Basic enemies.")
        self.assertEqual(preview.enemy_kinds, ("basic",))
        self.assertEqual(preview.enemy_names, ("Basic",))
        self.assertEqual(preview.threat, "low")
        self.assertEqual(preview.entrances, (Position(1, 13),))
        self.assertIsNone(preview.total_enemies)
        self.assertIsNone(preview.spawn_window_seconds)
        self.assertIsNone(preview.estimated_duration_seconds)
        self.assertEqual(preview.groups, ())
        self.assertEqual(preview.spawn_timeline, ())
        self.assertEqual(preview.primary_route, ())

    def test_detailed_intel_exposes_counts_and_timing(self) -> None:
        intel = self.intel_for(0)

        self.assertTrue(intel.is_detailed)
        self.assertEqual(intel.total_enemies, 5)
        self.assertEqual(len(intel.groups), 1)
        self.assertEqual(intel.groups[0].count, 5)
        self.assertEqual(intel.groups[0].entrance, Position(1, 13))
        self.assertEqual(intel.groups[0].last_spawn_seconds, 6.0)
        self.assertEqual(intel.spawn_window_seconds, 6.0)
        self.assertEqual(len(intel.spawn_timeline), 5)
        self.assertGreater(intel.estimated_duration_seconds or 0, 6.0)
        self.assertEqual(intel.primary_route, self.level.grid_map.path.points)

    def test_timeline_interleaves_mixed_groups_by_spawn_time(self) -> None:
        intel = self.intel_for(1)

        self.assertEqual(
            [
                (round(spawn.at_seconds, 6), spawn.enemy_kind)
                for spawn in intel.spawn_timeline
            ],
            [
                (0.0, "basic"),
                (1.2, "basic"),
                (2.0, "fast"),
                (2.4, "basic"),
                (3.6, "basic"),
                (3.8, "fast"),
                (4.8, "basic"),
                (5.6, "fast"),
            ],
        )
        self.assertIn("mixed", intel.tags)

    def test_enemy_traits_are_derived_from_templates(self) -> None:
        wave_intel = self.intel_for(2)
        self.assertIn("armored", wave_intel.tags)
        self.assertIn("mixed", wave_intel.tags)

        saboteur_intel = self.intel_for(3)
        self.assertIn("grid_saboteur", saboteur_intel.tags)
        self.assertIn("fast", saboteur_intel.tags)

    def test_authored_threat_overrides_derived_tier(self) -> None:
        wave = Wave(
            "Custom",
            "",
            (SpawnGroup("basic", 1, 1.0),),
            threat="high",
        )
        intel = build_wave_intel(wave, 0, (Position(1, 1),), (), 10.0)

        self.assertEqual(intel.threat, "high")

    def test_invalid_authored_threat_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "threat"):
            Wave("Bad", "", (SpawnGroup("basic", 1, 1.0),), threat="extreme")


if __name__ == "__main__":
    unittest.main()


class GameStateWaveIntelTest(unittest.TestCase):
    """Protect free/detailed intel reads, purchases, and snapshot wiring."""

    def setUp(self) -> None:
        self.game = GameState(create_demo_map())

    def test_free_intel_is_available_without_spending_gold(self) -> None:
        snapshot = self.game.snapshot()
        status = snapshot.status

        self.assertEqual(self.game.gold, 180)
        self.assertIsNotNone(status.free_intel)
        assert status.free_intel is not None
        self.assertFalse(status.free_intel.is_detailed)
        self.assertEqual(status.free_intel.wave_name, "Wave 1")
        self.assertIsNone(status.detailed_intel)
        self.assertEqual(status.intel_price, 8)

    def test_purchase_unlocks_structured_detail_and_snapshot_fields(self) -> None:
        briefing = self.game.buy_wave_intel()
        status = self.game.snapshot().status

        self.assertEqual(briefing, "Basic enemies.")
        self.assertEqual(self.game.gold, 172)
        self.assertIsNotNone(status.detailed_intel)
        assert status.detailed_intel is not None
        self.assertTrue(status.detailed_intel.is_detailed)
        self.assertEqual(status.detailed_intel.total_enemies, 5)
        self.assertEqual(len(status.detailed_intel.groups), 1)

    def test_repeat_purchase_does_not_charge_again(self) -> None:
        self.game.buy_wave_intel()
        gold_after_first = self.game.gold

        briefing = self.game.buy_wave_intel()

        self.assertEqual(briefing, "Basic enemies.")
        self.assertEqual(self.game.gold, gold_after_first)
        self.assertIsNotNone(self.game.detailed_wave_intel())

    def test_unlocks_are_scoped_to_the_current_wave(self) -> None:
        self.game.buy_wave_intel()
        self.game.start_next_wave()
        self.game.step(30.0)
        self.game.end_wave()

        self.assertEqual(self.game.wave_index, 1)
        self.assertIsNotNone(self.game.wave_intel())
        assert self.game.wave_intel() is not None
        self.assertEqual(self.game.wave_intel().wave_name, "Wave 2")
        self.assertIsNone(self.game.detailed_wave_intel())

    def test_custom_intel_price_is_used(self) -> None:
        game = GameState(create_demo_map(), intel_price=12)

        game.buy_wave_intel()

        self.assertEqual(game.gold, 168)
        self.assertEqual(game.snapshot().status.intel_price, 12)

    def test_from_level_uses_level_intel_price(self) -> None:
        level = load_demo_level()
        custom = replace(level, intel_price=5)
        game = GameState.from_level(custom)

        game.buy_wave_intel()

        self.assertEqual(game.gold, level.starting_gold - 5)

    def test_intel_cache_follows_replaced_waves(self) -> None:
        game = GameState(create_demo_map())
        game.waves = (Wave("Replacement", "One basic.", (SpawnGroup("basic", 1, 1.0),)),)

        intel = game.wave_intel()

        assert intel is not None
        self.assertEqual(intel.wave_name, "Replacement")
        self.assertEqual(intel.threat, "low")

    def test_no_waves_returns_no_intel_without_charging(self) -> None:
        game = GameState(create_demo_map(), waves=())

        self.assertIsNone(game.wave_intel())
        self.assertIsNone(game.detailed_wave_intel())
        self.assertEqual(game.buy_wave_intel(), "No incoming wave.")
        self.assertEqual(game.gold, 180)

    def test_terminal_game_rejects_purchase_without_mutation(self) -> None:
        self.game.core_hp = 0
        gold_before = self.game.gold

        with self.assertRaisesRegex(ValueError, "ended"):
            self.game.buy_wave_intel()

        self.assertEqual(self.game.gold, gold_before)
        self.assertIsNone(self.game.detailed_wave_intel())
