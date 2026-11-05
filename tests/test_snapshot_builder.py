"""Regression tests for the split snapshot builder and its static cache."""

import unittest
from dataclasses import replace

from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


class SnapshotBuilderCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game = GameState(create_demo_map())

    def test_static_terrain_refreshes_when_grid_map_is_replaced(self) -> None:
        before = self.game.cell_snapshot(Position(0, 0))
        self.assertEqual(before.terrain, "illegal")

        self.game.grid_map = replace(
            self.game.grid_map, illegal_ground_positions=frozenset()
        )

        after = self.game.cell_snapshot(Position(0, 0))
        self.assertEqual(after.terrain, "empty")
        self.assertTrue(after.is_buildable)

    def test_builder_is_reused_until_the_map_changes(self) -> None:
        first = self.game._snapshot_builder()
        self.assertIs(self.game._snapshot_builder(), first)

        self.game.grid_map = replace(self.game.grid_map)
        self.assertIsNot(self.game._snapshot_builder(), first)

    def test_status_snapshot_does_not_build_the_board(self) -> None:
        def fail() -> None:
            raise AssertionError("status_snapshot must not build the board")

        self.game.board_snapshot = fail  # type: ignore[method-assign]

        status = self.game.status_snapshot()

        self.assertEqual(status.gold, 180)
        self.assertEqual(status.core_hp, 30)


if __name__ == "__main__":
    unittest.main()
