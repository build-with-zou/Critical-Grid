"""Tests for derived wave intelligence."""

from __future__ import annotations

import unittest

from grid_td.intel import build_wave_intel, preview_wave_intel
from grid_td.levels import load_demo_level
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
