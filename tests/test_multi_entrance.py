"""Tests for maps with multiple enemy entrances."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from grid_td.game_state import GamePhase, GameState
from grid_td.levels import load_demo_level, load_level
from grid_td.map import create_demo_map
from grid_td.position import Position, WorldPosition
from grid_td.waves import SpawnGroup, Wave


MULTI_ENTRANCE_LEVEL = """\
name = "Multi Entrance"
description = "Two spawn points for testing."
starting_gold = 50
starting_core_hp = 10

[map]
width = 12
height = 9
core_position = [8, 3]
core_footprint = [3, 3]
route = [[1, 4], [7, 4]]
entrances = [[1, 4], [1, 1]]

[[waves]]
name = "Test Wave"
briefing = "Two entrances."

[[waves.groups]]
enemy_kind = "basic"
count = 1
interval_seconds = 1.0
start_delay_seconds = 0.0
entrance = 0

[[waves.groups]]
enemy_kind = "fast"
count = 1
interval_seconds = 1.0
start_delay_seconds = 0.0
entrance = 1
"""

LEGACY_LEVEL = """\
name = "Legacy Level"
starting_gold = 50
starting_core_hp = 10

[map]
width = 12
height = 9
core_position = [8, 3]
core_footprint = [3, 3]
route = [[1, 4], [7, 4]]

[[waves]]
name = "Legacy Wave"
briefing = "Single entrance."

[[waves.groups]]
enemy_kind = "basic"
count = 1
interval_seconds = 1.0
start_delay_seconds = 0.0
"""


class MultiEntranceTest(unittest.TestCase):
    """Protect entrance parsing, spawning, and build reservation."""

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.directory = Path(self._temporary_directory.name)

    def write_level(self, content: str) -> Path:
        path = self.directory / "level.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_demo_map_has_two_entrances(self) -> None:
        grid_map = create_demo_map()

        self.assertEqual(
            grid_map.spawn_entrances,
            (Position(1, 13), Position(35, 16)),
        )
        self.assertEqual(len(grid_map.route_cells), 165)
        self.assertTrue(all(grid_map.is_walkable(p) for p in grid_map.spawn_entrances))
        self.assertTrue(all(not grid_map.is_buildable(p) for p in grid_map.spawn_entrances))

    def test_loader_parses_entrances_and_group_assignment(self) -> None:
        level = load_level(self.write_level(MULTI_ENTRANCE_LEVEL))

        self.assertEqual(
            level.grid_map.spawn_entrances,
            (Position(1, 4), Position(1, 1)),
        )
        self.assertEqual(
            [group.entrance for group in level.waves[0].groups],
            [0, 1],
        )

    def test_spawns_from_distinct_entrances(self) -> None:
        level = load_level(self.write_level(MULTI_ENTRANCE_LEVEL))
        game = GameState.from_level(level)
        game.start_next_wave()
        game.step(0.0)

        snapshot = game.snapshot()
        enemies = [
            enemy
            for row in snapshot.board
            for cell in row
            for enemy in cell.enemies
        ]
        by_name = {enemy.name: enemy for enemy in enemies}

        self.assertEqual(set(by_name), {"Basic", "Fast"})
        self.assertEqual(by_name["Basic"].entrance_index, 0)
        self.assertEqual(by_name["Fast"].entrance_index, 1)
        self.assertEqual(
            by_name["Basic"].world_position,
            WorldPosition(1.5, 4.5),
        )
        self.assertEqual(
            by_name["Fast"].world_position,
            WorldPosition(1.5, 1.5),
        )
        self.assertEqual(
            snapshot.entrances,
            (Position(1, 4), Position(1, 1)),
        )

    def test_entrance_cells_cannot_be_built_on(self) -> None:
        game = GameState(create_demo_map())
        initial_gold = game.gold

        for anchor in (Position(1, 12), Position(33, 15)):
            with self.subTest(anchor=anchor):
                preview = game.preview_build("gun_tower", anchor)
                self.assertFalse(preview.is_valid)
                with self.assertRaises(ValueError):
                    game.build("gun_tower", anchor)
                self.assertEqual(game.gold, initial_gold)

    def test_invalid_group_entrance_is_rejected_without_state_change(self) -> None:
        game = GameState(create_demo_map())
        game.waves = (
            Wave(
                "Bad Wave",
                "",
                (SpawnGroup("basic", 1, 1.0, entrance=5),),
            ),
        )

        with self.assertRaises(ValueError):
            game.start_next_wave()

        self.assertEqual(game.phase, GamePhase.DAY)
        self.assertEqual(game.wave_index, 0)
        self.assertIsNone(game.wave_runner)

    def test_legacy_level_defaults_to_route_start(self) -> None:
        level = load_level(self.write_level(LEGACY_LEVEL))

        self.assertEqual(level.grid_map.spawn_entrances, (Position(1, 4),))
        self.assertEqual(level.waves[0].groups[0].entrance, 0)
        self.assertFalse(level.grid_map.is_buildable(Position(1, 4)))

    def test_duplicate_entrances_are_rejected(self) -> None:
        content = MULTI_ENTRANCE_LEVEL.replace(
            "entrances = [[1, 4], [1, 1]]",
            "entrances = [[1, 4], [1, 4]]",
        )
        with self.assertRaisesRegex(ValueError, "unique"):
            load_level(self.write_level(content))

    def test_first_entrance_must_match_route_start(self) -> None:
        content = MULTI_ENTRANCE_LEVEL.replace(
            "entrances = [[1, 4], [1, 1]]",
            "entrances = [[1, 1], [1, 4]]",
        )
        with self.assertRaisesRegex(ValueError, "route start"):
            load_level(self.write_level(content))

    def test_unreachable_entrance_is_rejected(self) -> None:
        content = MULTI_ENTRANCE_LEVEL.replace(
            "entrances = [[1, 4], [1, 1]]",
            (
                "entrances = [[1, 4], [1, 1]]\n\n[map.terrain]\n"
                "illegal = [\n"
                "  [0, 0, 1, 1], [1, 0, 1, 1], [2, 0, 1, 1],\n"
                "  [0, 1, 1, 1], [2, 1, 1, 1],\n"
                "  [0, 2, 1, 1], [1, 2, 1, 1], [2, 2, 1, 1],\n"
                "]"
            ),
        )
        with self.assertRaisesRegex(ValueError, "cannot reach the core"):
            load_level(self.write_level(content))

    def test_group_entrance_beyond_available_entrances_is_rejected(self) -> None:
        content = MULTI_ENTRANCE_LEVEL.replace(
            "entrance = 1",
            "entrance = 2",
        )
        with self.assertRaisesRegex(ValueError, "entrance"):
            load_level(self.write_level(content))

    def test_demo_spawn_snapshot_exposes_entrances(self) -> None:
        game = GameState.from_level(load_demo_level())
        snapshot = game.snapshot()

        self.assertEqual(
            snapshot.entrances,
            (Position(1, 13), Position(35, 16)),
        )


if __name__ == "__main__":
    unittest.main()
