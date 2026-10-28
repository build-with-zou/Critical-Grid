"""Headless range rendering regressions; run with python -m unittest gui.test_range_preview."""

from __future__ import annotations

import os
import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from grid_td.buildings import GunTower
from grid_td.game_state import BuildPreview, GameState
from grid_td.map import create_demo_map
from grid_td.position import Footprint, Position, WorldPosition
from grid_td.power_grid import PowerGrid
from gui.board_view import BoardView
from gui.gui import CriticalGridGUI
from gui.styles import (
    ATTACK_RANGE_COLOR, BACKGROUND, BOARD_LEFT, BOARD_TOP, CELL,
    POWER_RANGE_COLOR, UNCHARGED_COLOR, WINDOW_SIZE,
)


class RangeDrawingTest(unittest.TestCase):
    """Verify preview geometry, visibility, and clipping without changing the game."""

    def setUp(self) -> None:
        pygame.init()
        self.screen = pygame.display.set_mode(WINDOW_SIZE)
        self.board = BoardView(self.screen, pygame.font.SysFont("arial", 21))
        self.game = GameState(create_demo_map())
        self.snapshot = self.game.snapshot()

    def tearDown(self) -> None:
        pygame.quit()

    def preview(self, **overrides: object) -> BuildPreview:
        """Use the real public preview, varying only the case a drawing test needs."""
        footprint = self.game.preview_build("power_node", Position(30, 9))
        return replace(footprint, **overrides)

    def test_range_uses_candidate_center_and_includes_exact_boundary(self) -> None:
        cells = self.board._range_cells(self.snapshot, WorldPosition(16.5, 10.5), 6.0)
        for position in (Position(10, 10), Position(22, 10), Position(16, 4), Position(19, 13)):
            self.assertIn(position, cells)
        for position in (Position(9, 10), Position(23, 10), Position(20, 13)):
            self.assertNotIn(position, cells)

    def test_even_footprint_centers_are_preserved(self) -> None:
        cells = self.board._range_cells(self.snapshot, WorldPosition(4.0, 6.0), 1.0)
        self.assertEqual(cells, frozenset((
            Position(3, 5), Position(4, 5), Position(3, 6), Position(4, 6),
        )))

    def test_node_and_tower_ranges_have_distinct_colors(self) -> None:
        for preview, color in (
            (self.preview(), POWER_RANGE_COLOR),
            (self.preview(power_radius=None, attack_range=9.0), ATTACK_RANGE_COLOR),
        ):
            with self.subTest(color=color), patch.object(self.board, "_draw_range_cells") as draw:
                self.board._draw_build_range(self.snapshot, preview)
                draw.assert_called_once_with(
                    self.snapshot, preview.center,
                    preview.power_radius if preview.power_radius is not None else preview.attack_range,
                    color,
                )

    def test_invalid_placement_keeps_coverage_visible_in_red(self) -> None:
        preview = self.preview(is_valid=False, reason="Not enough gold.")
        with patch.object(self.board, "_draw_range_cells") as draw:
            self.board._draw_build_range(self.snapshot, preview)
            draw.assert_called_once_with(self.snapshot, preview.center, 6.0, UNCHARGED_COLOR)

    def test_legacy_previews_and_non_transmitters_have_no_invented_range(self) -> None:
        with patch.object(self.board, "_draw_range_cells") as draw:
            self.board._draw_build_range(
                self.snapshot, BuildPreview(
                    "power_node", Position(30, 9), 3, 3, (), True, "",
                ),
            )
            self.board._draw_build_range(self.snapshot, self.preview(power_radius=None))
            draw.assert_not_called()

    def test_off_board_coverage_stays_inside_the_map(self) -> None:
        self.screen.fill(BACKGROUND)
        self.board._draw_range_cells(self.snapshot, WorldPosition(0.5, 0.5), 6.0, POWER_RANGE_COLOR)
        self.assertEqual(tuple(self.screen.get_at((BOARD_LEFT - 1, BOARD_TOP)))[:3], BACKGROUND)
        self.assertEqual(tuple(self.screen.get_at((BOARD_LEFT, BOARD_TOP - 1)))[:3], BACKGROUND)
        self.assertNotEqual(tuple(self.screen.get_at((BOARD_LEFT + 5, BOARD_TOP + 5)))[:3], BACKGROUND)

    def test_out_of_bounds_footprint_restores_existing_clip(self) -> None:
        clip = pygame.Rect(BOARD_LEFT, BOARD_TOP, 100, 100)
        self.screen.set_clip(clip)
        preview = self.preview(position=Position(35, 20), is_valid=False)
        self.board._draw_preview(preview, pygame.Rect(BOARD_LEFT, BOARD_TOP, 36 * CELL, 21 * CELL))
        self.assertEqual(self.screen.get_clip(), clip)

    def test_candidate_range_is_drawn_before_units_and_footprint(self) -> None:
        calls = []
        with (
            patch.object(self.board, "_draw_build_range", side_effect=lambda *args: calls.append("range")),
            patch.object(self.board, "_draw_enemies", side_effect=lambda *args: calls.append("enemies")),
            patch.object(self.board, "_draw_buildings", side_effect=lambda *args: calls.append("buildings")),
            patch.object(self.board, "_draw_preview", side_effect=lambda *args: calls.append("footprint")),
        ):
            self.board.draw(self.snapshot, None, None, Position(30, 9), self.preview())
        self.assertEqual(calls, ["range", "buildings", "enemies", "footprint"])

    def test_rendering_does_not_build_spend_gold_or_mutate_game_state(self) -> None:
        before = self.game.snapshot()
        self.board.draw(self.snapshot, None, None, Position(30, 9), self.preview())
        self.assertEqual(self.game.snapshot(), before)

    def test_real_cursor_hover_draws_node_and_all_tower_types_before_placement(self) -> None:
        gui = CriticalGridGUI()
        gui.view = "game"
        before = gui.game.snapshot()
        anchor = Position(30, 9)
        mouse = (BOARD_LEFT + anchor.x * CELL + CELL // 2, BOARD_TOP + anchor.y * CELL + CELL // 2)
        for kind in ("power_node", "gun_tower", "cannon_tower", "slow_tower"):
            with self.subTest(kind=kind):
                button = next(button for button, value in gui.sidebar.build_buttons.items() if value == kind)
                gui._handle_button(button)
                with (
                    patch("pygame.mouse.get_pos", return_value=mouse),
                    patch("pygame.quit"),
                    patch.object(gui.board, "_draw_range_cells", wraps=gui.board._draw_range_cells) as draw,
                ):
                    gui.run(max_frames=1)
                    draw.assert_called_once()
                    self.assertEqual(draw.call_args.args[1], WorldPosition(31.5, 10.5))
                    self.assertEqual(draw.call_args.args[2], 6.0)
                self.assertEqual(gui.game.snapshot(), before)

    def test_leaving_map_or_cancelling_build_clears_hover_range(self) -> None:
        gui = CriticalGridGUI()
        gui.view = "game"
        gui.selected_kind = "power_node"
        with (
            patch("pygame.mouse.get_pos", return_value=(0, 0)),
            patch("pygame.quit"),
            patch.object(gui.board, "_draw_build_range") as draw,
        ):
            gui.run(max_frames=1)
            draw.assert_not_called()
        gui._cancel_build()
        with (
            patch("pygame.mouse.get_pos", return_value=(BOARD_LEFT + 30 * CELL, BOARD_TOP + 9 * CELL)),
            patch("pygame.quit"),
            patch.object(gui.board, "_draw_build_range") as draw,
        ):
            gui.run(max_frames=1)
            draw.assert_not_called()


class PreviewContractTest(unittest.TestCase):
    """Keep presentation ranges aligned with actual placement and grid configuration."""

    def setUp(self) -> None:
        self.game = GameState(create_demo_map())

    def test_node_reach_uses_the_configured_grid_radius(self) -> None:
        for radius in (0.0, 4.5, 9.0):
            with self.subTest(radius=radius):
                self.game.power_grid = PowerGrid(connection_radius=radius)
                preview = self.game.preview_build("power_node", Position(30, 9))
                self.assertEqual(preview.power_radius, radius)
                self.assertEqual(preview.center, WorldPosition(31.5, 10.5))
                self.assertIsNone(preview.attack_range)

    def test_all_tower_previews_match_the_range_of_the_built_tower(self) -> None:
        for kind in ("gun_tower", "cannon_tower", "slow_tower"):
            # Full high ground grants the bonus; partial coverage must not.
            for position, expected_range in ((Position(12, 6), 9.0), (Position(13, 6), 6.0)):
                with self.subTest(kind=kind, position=position):
                    game = GameState(create_demo_map())
                    preview = game.preview_build(kind, position)
                    self.assertTrue(preview.is_valid)
                    self.assertEqual(preview.attack_range, expected_range)
                    self.assertIsNone(preview.power_radius)
                    built = game.build(kind, position)
                    actual = game.snapshot().board[position.y][position.x].building
                    self.assertEqual(preview.center, actual.center)
                    self.assertEqual(preview.attack_range, actual.range)
                    self.assertEqual(preview.center, built.center)

    def test_preview_uses_actual_rectangular_footprint_center(self) -> None:
        with patch.object(GunTower, "FOOTPRINT", Footprint(2, 4)):
            preview = self.game.preview_build("gun_tower", Position(30, 6))
            self.assertEqual((preview.width, preview.height), (2, 4))
            self.assertEqual(preview.center, WorldPosition(31.0, 8.0))

    def test_repeated_hover_never_spends_gold_allocates_ids_or_changes_power(self) -> None:
        before = self.game.snapshot()
        next_id = self.game.next_building_id
        for kind in ("power_node", "power_plant", "gun_tower", "cannon_tower", "slow_tower"):
            for position in (Position(30, 9), Position(12, 6), Position(35, 20)):
                self.game.preview_build(kind, position)
        self.assertEqual(self.game.snapshot(), before)
        self.assertEqual(self.game.next_building_id, next_id)

    def test_invalid_placements_still_expose_ranges_and_rejection_reason(self) -> None:
        poor_game = GameState(create_demo_map(), gold=0)
        for kind, position in (
            ("power_node", Position(30, 9)), ("gun_tower", Position(35, 20)),
            ("cannon_tower", Position(0, 12)),
        ):
            with self.subTest(kind=kind):
                preview = poor_game.preview_build(kind, position)
                self.assertFalse(preview.is_valid)
                self.assertTrue(preview.reason)
                self.assertIsNotNone(preview.center)
                self.assertIsNotNone(preview.power_radius if kind == "power_node" else preview.attack_range)

    def test_mines_have_no_range_and_plants_expose_transmitter_reach(self) -> None:
        mine = self.game.preview_build("mine", Position(6, 3))
        plant = self.game.preview_build("power_plant", Position(30, 9))
        self.assertIsNone(mine.attack_range)
        self.assertIsNone(mine.power_radius)
        self.assertIsNone(plant.attack_range)
        self.assertEqual(plant.power_radius, self.game.power_grid.connection_radius)

    def test_range_fields_remain_immutable(self) -> None:
        preview = self.game.preview_build("power_node", Position(30, 9))
        for name, value in (("center", WorldPosition(0.0, 0.0)), ("power_radius", 99.0), ("attack_range", 99.0)):
            with self.subTest(field=name), self.assertRaises(FrozenInstanceError):
                setattr(preview, name, value)


if __name__ == "__main__":
    unittest.main()
