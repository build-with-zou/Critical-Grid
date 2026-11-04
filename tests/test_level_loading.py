"""Tests for TOML-backed level loading and GameState integration."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from grid_td.game_state import GamePhase, GameState
from grid_td.levels import load_demo_level, load_level
from grid_td.map import create_demo_map
from grid_td.position import Position
from grid_td.waves import create_demo_waves


MINIMAL_LEVEL = """\
name = "Test Level"
description = "A small test level."
starting_gold = 50
starting_core_hp = 10

[map]
width = 12
height = 9
core_position = [6, 3]
core_footprint = [3, 3]
route = [[1, 4], [5, 4]]

[[waves]]
name = "Test Wave"
briefing = "Basic test."

[[waves.groups]]
enemy_kind = "basic"
count = 1
interval_seconds = 1.0
start_delay_seconds = 0.0
"""


class LevelLoadingTest(unittest.TestCase):
    """Protect the level schema, demo parity, and GameState integration."""

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.directory = Path(self._temporary_directory.name)

    def write_level(self, content: str, name: str = "level.toml") -> Path:
        path = self.directory / name
        path.write_text(content, encoding="utf-8")
        return path

    def assert_invalid(self, content: str, message: str = "") -> None:
        with self.assertRaisesRegex(ValueError, message):
            load_level(self.write_level(content))

    def test_demo_level_matches_current_demo_geometry(self) -> None:
        level = load_demo_level()
        grid_map = level.grid_map

        self.assertEqual((grid_map.width, grid_map.height), (36, 21))
        self.assertEqual(grid_map.path.length, 36)
        self.assertEqual(len(grid_map.route_cells), 165)
        self.assertTrue(grid_map.is_route(Position(7, 13)))
        self.assertTrue(grid_map.is_route(Position(35, 16)))
        self.assertEqual(
            grid_map.spawn_entrances,
            (Position(1, 13), Position(35, 16)),
        )
        self.assertFalse(grid_map.is_buildable(Position(1, 13)))
        self.assertFalse(grid_map.is_buildable(Position(35, 16)))
        self.assertFalse(grid_map.is_route(Position(7, 11)))
        self.assertTrue(grid_map.is_mine_site(Position(8, 5)))
        self.assertTrue(grid_map.is_high_ground(Position(12, 6)))
        self.assertTrue(grid_map.is_high_ground(Position(21, 6)))
        self.assertTrue(grid_map.is_illegal(Position(33, 6)))
        self.assertTrue(grid_map.is_core(Position(32, 5)))
        self.assertFalse(grid_map.is_core(Position(29, 5)))

    def test_demo_level_matches_current_demo_waves(self) -> None:
        waves = load_demo_level().waves
        self.assertEqual(len(waves), 4)
        self.assertEqual(
            [wave.name for wave in waves],
            ["Wave 1", "Wave 2", "Wave 3", "Wave 4"],
        )
        self.assertEqual(
            [wave.briefing for wave in waves],
            [
                "Basic enemies.",
                "Fast enemies mixed with basic enemies.",
                "Armored enemies test sustained damage.",
                "Saboteurs appear. Protect the grid.",
            ],
        )
        self.assertEqual(
            [
                (group.enemy_kind, group.count, group.interval_seconds, group.start_delay_seconds)
                for group in waves[0].groups
            ],
            [("basic", 5, 1.5, 0.0)],
        )
        self.assertEqual(
            [
                (group.enemy_kind, group.count, group.interval_seconds, group.start_delay_seconds)
                for group in waves[1].groups
            ],
            [("basic", 5, 1.2, 0.0), ("fast", 3, 1.8, 2.0)],
        )
        self.assertEqual(
            [
                (group.enemy_kind, group.count, group.interval_seconds, group.start_delay_seconds)
                for group in waves[2].groups
            ],
            [("basic", 4, 1.0, 0.0), ("armored", 3, 2.5, 1.0)],
        )
        self.assertEqual(
            [
                (group.enemy_kind, group.count, group.interval_seconds, group.start_delay_seconds)
                for group in waves[3].groups
            ],
            [("fast", 4, 1.2, 0.0), ("saboteur", 3, 2.0, 1.5)],
        )

    def test_demo_starting_resources(self) -> None:
        level = load_demo_level()
        self.assertEqual(level.name, "Frontier Demo")
        self.assertEqual(level.starting_gold, 180)
        self.assertEqual(level.starting_core_hp, 30)

    def test_intel_price_defaults_and_parses_custom_values(self) -> None:
        self.assertEqual(load_level(self.write_level(MINIMAL_LEVEL)).intel_price, 8)

        custom = MINIMAL_LEVEL.replace(
            'starting_core_hp = 10\n',
            'starting_core_hp = 10\nintel_price = 12\n',
        )
        self.assertEqual(load_level(self.write_level(custom)).intel_price, 12)

    def test_invalid_intel_price_is_rejected(self) -> None:
        negative = MINIMAL_LEVEL.replace(
            'starting_core_hp = 10\n',
            'starting_core_hp = 10\nintel_price = -1\n',
        )
        self.assert_invalid(negative, "intel_price")

    def test_wave_threat_parses_and_invalid_values_are_rejected(self) -> None:
        authored = MINIMAL_LEVEL.replace(
            'briefing = "Basic test."\n',
            'briefing = "Basic test."\nthreat = "high"\n',
        )
        level = load_level(self.write_level(authored))
        self.assertEqual(level.waves[0].threat, "high")

        invalid = MINIMAL_LEVEL.replace(
            'briefing = "Basic test."\n',
            'briefing = "Basic test."\nthreat = "extreme"\n',
        )
        self.assert_invalid(invalid, "threat")

    def test_legacy_helpers_load_the_demo_file(self) -> None:
        level = load_demo_level()
        self.assertEqual(create_demo_map(), level.grid_map)
        self.assertEqual(create_demo_waves(), level.waves)

    def test_from_level_uses_level_resources_and_waves(self) -> None:
        level = load_level(self.write_level(MINIMAL_LEVEL))
        game = GameState.from_level(level)

        self.assertEqual(game.phase, GamePhase.DAY)
        self.assertEqual(game.gold, 50)
        self.assertEqual(game.core_hp, 10)
        self.assertEqual(game.waves, level.waves)
        self.assertEqual(game.current_wave_name, "Test Wave")

    def test_custom_level_can_start_and_step(self) -> None:
        level = load_level(self.write_level(MINIMAL_LEVEL))
        game = GameState.from_level(level)

        game.start_next_wave()
        game.step(1.0)

        self.assertEqual(game.phase, GamePhase.NIGHT)
        self.assertEqual(len(game.enemies), 1)
        self.assertEqual(game.enemies[0].name, "Basic")

    def test_missing_file_raises_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_level(self.directory / "missing.toml")

    def test_invalid_toml_is_rejected(self) -> None:
        self.assert_invalid("name = [", "invalid TOML")

    def test_missing_required_field_is_rejected(self) -> None:
        self.assert_invalid(
            MINIMAL_LEVEL.replace("starting_gold = 50\n", ""),
            "starting_gold",
        )

    def test_unknown_level_field_is_rejected(self) -> None:
        self.assert_invalid(
            MINIMAL_LEVEL.replace(
                "starting_core_hp = 10\n",
                "starting_core_hp = 10\nextra = 1\n",
            ),
            "unknown field",
        )

    def test_unknown_map_field_is_rejected(self) -> None:
        self.assert_invalid(
            MINIMAL_LEVEL.replace("[map]\n", "[map]\nextra = 1\n"),
            "unknown field",
        )

    def test_unknown_enemy_kind_is_rejected(self) -> None:
        self.assert_invalid(
            MINIMAL_LEVEL.replace('enemy_kind = "basic"', 'enemy_kind = "ghost"'),
            "Unknown enemy kind",
        )

    def test_zero_count_is_rejected(self) -> None:
        self.assert_invalid(
            MINIMAL_LEVEL.replace("count = 1", "count = 0"),
            "count",
        )

    def test_non_positive_interval_is_rejected(self) -> None:
        self.assert_invalid(
            MINIMAL_LEVEL.replace("interval_seconds = 1.0", "interval_seconds = 0.0"),
            "interval_seconds",
        )

    def test_negative_start_delay_is_rejected(self) -> None:
        self.assert_invalid(
            MINIMAL_LEVEL.replace("start_delay_seconds = 0.0", "start_delay_seconds = -1.0"),
            "start_delay_seconds",
        )

    def test_rectangle_outside_map_is_rejected(self) -> None:
        content = MINIMAL_LEVEL.replace(
            "route = [[1, 4], [5, 4]]",
            "route = [[1, 4], [5, 4]]\n\n[map.terrain]\nmine = [[0, 0, 13, 3]]",
        )
        self.assert_invalid(content, "outside the map")

    def test_overlapping_terrain_is_rejected(self) -> None:
        content = MINIMAL_LEVEL.replace(
            "route = [[1, 4], [5, 4]]",
            (
                "route = [[1, 4], [5, 4]]\n\n[map.terrain]\n"
                "mine = [[0, 0, 3, 3]]\n"
                "high_ground = [[0, 0, 3, 3]]"
            ),
        )
        self.assert_invalid(content, "overlaps high_ground")

    def test_terrain_overlapping_core_is_rejected(self) -> None:
        content = MINIMAL_LEVEL.replace(
            "route = [[1, 4], [5, 4]]",
            "route = [[1, 4], [5, 4]]\n\n[map.terrain]\nmine = [[6, 3, 3, 3]]",
        )
        self.assert_invalid(content, "core footprint")

    def test_road_must_cover_the_route_centerline(self) -> None:
        content = MINIMAL_LEVEL.replace(
            "route = [[1, 4], [5, 4]]",
            (
                "route = [[1, 4], [5, 4]]\n\n[map.terrain]\n"
                "road = [[0, 0, 1, 1]]"
            ),
        )
        self.assert_invalid(content, "Road terrain must cover")

    def test_route_outside_map_is_rejected(self) -> None:
        self.assert_invalid(
            MINIMAL_LEVEL.replace(
                "route = [[1, 4], [5, 4]]",
                "route = [[1, 4], [99, 4]]",
            ),
            "Route waypoints",
        )

    def test_route_through_core_is_rejected(self) -> None:
        self.assert_invalid(
            MINIMAL_LEVEL.replace(
                "route = [[1, 4], [5, 4]]",
                "route = [[1, 4], [7, 4]]",
            ),
            "not walkable",
        )

    def test_duplicate_wave_names_are_rejected(self) -> None:
        duplicate = MINIMAL_LEVEL + """
[[waves]]
name = "Test Wave"
briefing = "Duplicate"

[[waves.groups]]
enemy_kind = "basic"
count = 1
interval_seconds = 1.0
start_delay_seconds = 0.0
"""
        self.assert_invalid(duplicate, "duplicate wave name")

    def test_empty_waves_are_rejected(self) -> None:
        content = """\
name = "Empty Waves"
starting_gold = 50
starting_core_hp = 10
waves = []

[map]
width = 12
height = 9
core_position = [6, 3]
core_footprint = [3, 3]
route = [[1, 4], [5, 4]]
"""
        self.assert_invalid(content, "waves")


if __name__ == "__main__":
    unittest.main()
