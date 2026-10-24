"""Headless GUI command regressions; run with python -m unittest gui.test_interactions."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

# These tests exercise real widgets and rendering without opening a desktop window.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from grid_td.buildings import GunTower, PowerPlant
from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position
from gui.gui import CriticalGridGUI
from gui.sidebar import Sidebar
from gui.styles import BOARD_LEFT, BOARD_TOP, CELL


class BuildingInteractionTest(unittest.TestCase):
    """Verify selection, public command routing, and fresh snapshot feedback."""

    def setUp(self) -> None:
        self.gui = CriticalGridGUI()
        self.gui.view = "game"

    def tearDown(self) -> None:
        pygame.quit()

    def click_cell(self, position: Position) -> None:
        """Send a map click through the same pixel-to-cell path as player input."""
        self.gui._handle_board_click((
            BOARD_LEFT + position.x * CELL + CELL // 2,
            BOARD_TOP + position.y * CELL + CELL // 2,
        ))

    def test_all_non_core_kinds_can_be_selected_and_sold(self) -> None:
        for kind in ("mine", "power_plant", "power_node", "gun_tower", "cannon_tower", "slow_tower"):
            with self.subTest(kind=kind):
                self.gui.game = GameState(create_demo_map())
                snapshot = self.gui.game.snapshot()
                position = next(
                    cell.position for row in snapshot.board for cell in row
                    if self.gui.game.preview_build(kind, cell.position).is_valid
                )
                self.gui.game.build(kind, position)
                # An interior footprint cell must select the entire building.
                self.click_cell(Position(position.x + 1, position.y + 1))
                selected = self.gui._selected_building(self.gui.game.snapshot())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.kind, kind)
                before = self.gui.game.snapshot().status.gold
                self.gui._handle_button(self.gui.sidebar.sell_button)
                after = self.gui.game.snapshot()
                self.assertEqual(after.status.gold - before, round(selected.cost * 0.7))
                self.assertIsNone(after.board[position.y][position.x].building)
                self.assertIsNone(self.gui.selected_building_id)
                self.assertIn("Refund +", self.gui.message)

    def test_repair_restores_hp_and_refreshes_damaged_plant_supply(self) -> None:
        plant = PowerPlant(50, Position(30, 6))
        plant.take_damage(plant.max_hp // 2)
        self.gui.game = GameState(create_demo_map(), buildings=[plant])
        self.click_cell(plant.position)
        before = self.gui.game.snapshot()
        cost = self.gui._selected_building(before).repair_cost
        self.gui._handle_button(self.gui.sidebar.repair_button)
        after = self.gui.game.snapshot()
        selected = self.gui._selected_building(after)
        self.assertEqual(selected.hp, selected.max_hp)
        self.assertEqual(before.status.gold - after.status.gold, cost)
        self.assertGreater(after.status.power.total_supply, before.status.power.total_supply)
        self.assertIn(f"Spent {cost} gold", self.gui.message)

    def test_core_is_selectable_and_repairable_but_cannot_be_sold(self) -> None:
        self.gui.game = GameState(create_demo_map(), core_hp=25)
        self.click_cell(Position(30, 3))
        before = self.gui.game.snapshot()
        self.gui._sell_selected_building()
        self.assertEqual(self.gui.game.snapshot(), before)
        self.assertIn("core cannot be sold", self.gui.message)
        self.gui._repair_selected_building()
        self.assertEqual(self.gui.game.snapshot().status.core_hp, 30)

    def test_hp_repair_preserves_overload_service_marker(self) -> None:
        tower = GunTower(50, Position(27, 0))
        tower.take_damage(1)
        self.gui.game = GameState(create_demo_map(), buildings=[tower])
        self.gui.game.overload_tower(tower.id)
        self.click_cell(tower.position)
        self.gui._repair_selected_building()
        selected = self.gui._selected_building(self.gui.game.snapshot())
        self.assertEqual(selected.repair_cost, 0)
        self.assertTrue(selected.needs_repair)
        self.gui.sidebar.update_actions(self.gui.game.snapshot(), selected)
        self.assertFalse(self.gui.sidebar.repair_button.is_enabled)
        self.assertIn("Overload service: due at settlement", Sidebar.inspection_lines(
            self.gui.game.snapshot(), tower.position,
        ))

    def test_rejected_repair_keeps_selection_and_displays_core_reason(self) -> None:
        plant = PowerPlant(50, Position(30, 6))
        plant.take_damage(1)
        self.gui.game = GameState(create_demo_map(), gold=0, buildings=[plant])
        self.click_cell(plant.position)
        before = self.gui.game.snapshot()
        self.gui._repair_selected_building()
        self.assertEqual(self.gui.game.snapshot(), before)
        self.assertEqual(self.gui.selected_building_id, plant.id)
        self.assertIn("Not enough gold", self.gui.message)

    def test_details_distinguish_rated_supply_health_and_power_efficiency(self) -> None:
        plant = PowerPlant(50, Position(30, 6))
        plant.take_damage(plant.max_hp // 2)
        self.gui.game = GameState(create_demo_map(), buildings=[plant])
        lines = "\n".join(Sidebar.inspection_lines(self.gui.game.snapshot(), plant.position))
        for label in ("Power eff.", "Health eff.", "Final eff.", "Rated supply", "Full repair:"):
            self.assertIn(label, lines)

    def test_rejected_sale_displays_reason_without_dropping_selection(self) -> None:
        self.gui.game.build("power_node", Position(30, 9))
        self.click_cell(Position(30, 9))
        selected_id = self.gui.selected_building_id
        with patch.object(self.gui.game, "sell_building", side_effect=ValueError("Sale rejected.")):
            self.gui._sell_selected_building()
        self.assertEqual(self.gui.message, "Sale rejected.")
        self.assertEqual(self.gui.selected_building_id, selected_id)

    def test_playable_view_renders_with_lifecycle_controls(self) -> None:
        self.click_cell(Position(30, 3))
        self.gui.run(max_frames=2)


if __name__ == "__main__":
    unittest.main()
