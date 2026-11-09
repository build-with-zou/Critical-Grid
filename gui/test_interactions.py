"""Headless GUI command regressions; run with python -m unittest gui.test_interactions."""

from __future__ import annotations

import os
import unittest
from dataclasses import replace
from unittest.mock import patch

# These tests exercise real widgets and rendering without opening a desktop window.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from grid_td.buildings import GunTower, PowerNode, PowerPlant, PowerPriority
from grid_td.enemies import create_enemy
from grid_td.game_state import GamePhase, GameState
from grid_td.levels import load_demo_level
from grid_td.map import create_demo_map
from grid_td.position import Position
from gui.gui import CriticalGridGUI
from gui.intel_view import detail_lines, overview_lines
from gui.sidebar import Sidebar
from gui.styles import BOARD_LEFT, BOARD_TOP, CELL, LIMITED_COLOR


class BuildingInteractionTest(unittest.TestCase):
    """Verify selection, public command routing, and fresh snapshot feedback."""

    def setUp(self) -> None:
        self.gui = CriticalGridGUI()
        self.gui.view = "game"

    def tearDown(self) -> None:
        pygame.quit()

    def test_intel_button_tracks_level_price_and_charges_once(self) -> None:
        level = load_demo_level()
        self.gui.game = GameState.from_level(replace(level, intel_price=12))
        button = self.gui.sidebar.intel_button
        before = self.gui.game.snapshot()
        self.gui.sidebar.update_actions(before, None)
        self.assertEqual(button.text, "Wave Intel (12g)")
        self.assertIn("12 gold", button.tool_tip_text)
        self.gui._handle_button(button)
        after = self.gui.game.snapshot()
        self.assertEqual(before.status.gold - after.status.gold, 12)
        self.assertIsNotNone(after.status.detailed_intel)
        self.assertIn("-12 gold", self.gui.message)
        self.assertIn("Estimated duration", self.gui.intel.details.html_text)
        self.gui.sidebar.update_actions(after, None)
        self.assertEqual(button.text, "Intel Unlocked")
        self.gui._handle_button(button)
        self.assertEqual(self.gui.game.snapshot().status.gold, after.status.gold)

    def test_intel_overview_and_detail_pages_use_map_entrance_numbers(self) -> None:
        level = load_demo_level()
        self.gui.game = GameState.from_level(replace(level, waves=(level.waves[-1],)))
        before = self.gui.game.snapshot()
        overview = "\n".join(overview_lines(before))
        for label in ("Wave 8", "Threat: High", "Saboteur", "Traits:", "Entrances: E1, E2",
                      level.waves[-1].briefing):
            self.assertIn(label, overview)
        self.assertIsNone(before.status.detailed_intel)
        self.assertNotIn("Estimated duration", "\n".join(detail_lines(before)))
        self.assertNotIn("Spawn window", overview)
        self.gui._handle_button(self.gui.sidebar.intel_button)
        after = self.gui.game.snapshot()
        details = after.status.detailed_intel
        self.assertIn(f"{details.total_enemies} enemies", self.gui.intel.details.html_text)
        for group in details.groups:
            self.assertIn(f"{group.count} × {group.enemy_name}  E{group.entrance_index + 1}",
                          self.gui.intel.details.html_text)
        self.gui._handle_button(self.gui.intel.timeline_button)
        first, last = details.spawn_timeline[0], details.spawn_timeline[-1]
        for spawn in (first, last):
            self.assertIn(f"{spawn.at_seconds:g}s  {spawn.enemy_name}  E{spawn.entrance_index + 1}",
                          self.gui.intel.details.html_text)
        self.assertTrue(self.gui.intel.timeline_button.is_selected)
        self.gui._handle_button(self.gui.intel.groups_button)
        self.assertIn("Interval", self.gui.intel.details.html_text)

    def test_intel_remains_available_at_night_and_resets_after_settlement(self) -> None:
        self.gui.game.start_next_wave()
        night = self.gui.game.snapshot()
        self.gui.sidebar.update_actions(night, None)
        self.assertTrue(self.gui.sidebar.intel_button.is_enabled)
        self.gui._handle_button(self.gui.sidebar.intel_button)
        self.gui._handle_button(self.gui.intel.timeline_button)
        self.gui.game.step(30.0)
        self.gui.game.end_wave()
        next_wave = self.gui.game.snapshot()
        self.gui.sidebar.update_actions(next_wave, None)
        self.gui.intel.update(next_wave)
        self.assertIn("Wave 2", self.gui.intel.overview.html_text)
        self.assertIsNone(next_wave.status.detailed_intel)
        self.assertFalse(self.gui.intel.timeline_button.visible)
        self.assertNotIn("Estimated duration", self.gui.intel.details.html_text)
        self.assertIn(f"{next_wave.status.intel_price}g", self.gui.sidebar.intel_button.text)

    def test_zero_price_and_insufficient_gold_use_core_purchase_results(self) -> None:
        level = load_demo_level()
        button = self.gui.sidebar.intel_button
        for price in (0, 12):
            with self.subTest(price=price):
                self.gui.game = GameState.from_level(replace(level, intel_price=price, starting_gold=0))
                before = self.gui.game.snapshot()
                self.gui.sidebar.update_actions(before, None)
                if price == 0:
                    self.assertEqual(button.text, "Wave Intel (Free)")
                self.gui._handle_button(button)
                after = self.gui.game.snapshot()
                self.assertEqual(after.status.gold, before.status.gold)
                if price == 0:
                    self.assertIsNotNone(after.status.detailed_intel)
                else:
                    self.assertIsNone(after.status.detailed_intel)
                    self.assertIn("Not enough gold", self.gui.message)

    def test_purchase_control_disabled_without_wave_or_after_core_destruction(self) -> None:
        before = self.gui.game.snapshot()
        button = self.gui.sidebar.intel_button
        for changes in ({"free_intel": None}, {"core_hp": 0}, {"is_finished": True}):
            with self.subTest(changes=changes):
                snapshot = replace(before, status=replace(before.status, **changes))
                self.gui.sidebar.update_actions(snapshot, None)
                self.gui.intel.update(snapshot)
                self.assertFalse(button.is_enabled)
                self.assertFalse(self.gui.intel.timeline_button.visible)
                if snapshot.status.free_intel is None:
                    self.assertEqual(button.text, "No Wave Intel")
                    self.assertIn("No incoming wave.", self.gui.intel.overview.html_text)

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

    def test_priority_button_routes_through_game_state(self) -> None:
        tower = self.gui.game.build("gun_tower", Position(30, 6))
        self.click_cell(tower.position)
        self.assertEqual(tower.power_priority, PowerPriority.HIGH)
        self.gui._handle_button(self.gui.sidebar.priority_button)
        self.assertEqual(tower.power_priority, PowerPriority.MEDIUM)
        self.assertIn("MEDIUM", self.gui.message)

    def test_priority_control_does_not_cover_selected_tower_details(self) -> None:
        tower = self.gui.game.build("cannon_tower", Position(30, 6))
        snapshot = self.gui.game.snapshot()
        sidebar = self.gui.sidebar
        with patch.object(sidebar, "_text", wraps=sidebar._text) as draw_text:
            sidebar.draw(snapshot, None, tower.position)
        details = [call.args for call in draw_text.call_args_list if call.args[0] != "BUILD"]
        for label, x, y, _ in details:
            text_rect = pygame.Rect((x, y), sidebar.font.size(label))
            self.assertFalse(text_rect.colliderect(sidebar.priority_button.get_abs_rect()), label)
            self.assertLessEqual(text_rect.bottom, 738, label)
            self.assertLessEqual(text_rect.width, 315, label)

    def test_selected_consumer_shows_attenuated_link_and_direct_source(self) -> None:
        node = PowerNode(50, Position(30, 9))
        node.take_damage(node.max_hp // 2)
        self.gui.game = GameState(create_demo_map(), buildings=[node])
        tower = self.gui.game.build("gun_tower", Position(30, 15))
        snapshot = self.gui.game.snapshot()
        building = snapshot.board[15][30].building
        self.assertEqual(building.power_source_id, node.id)
        self.assertLess(building.transmission_efficiency, 1.0)
        self.gui.board.draw(snapshot, tower.id, tower.position, None, None)
        middle = (BOARD_LEFT + round(31.5 * CELL), BOARD_TOP + round(13.5 * CELL))
        self.assertEqual(tuple(self.gui.screen.get_at(middle))[:3], LIMITED_COLOR)
        self.assertIn(f"Direct source: #{node.id}  Demand {tower.power_draw}",
                      Sidebar.inspection_lines(snapshot, tower.position))

    def test_menu_and_game_use_the_same_level_definition(self) -> None:
        level = replace(load_demo_level(), name="Test Frontier", starting_gold=245, starting_core_hp=36)
        with patch("gui.gui.load_demo_level", return_value=level):
            gui = CriticalGridGUI()
        snapshot = gui.game.snapshot()
        self.assertEqual((snapshot.status.gold, snapshot.status.core_hp), (245, 36))
        self.assertEqual(snapshot.entrances, level.grid_map.spawn_entrances)
        self.assertIn("Entrance E2", Sidebar.inspection_lines(snapshot, snapshot.entrances[1])[0])
        with patch.object(gui.menu, "_text", wraps=gui.menu._text) as draw_text:
            gui.menu.draw("levels", (0, 0))
        self.assertIn("TEST FRONTIER", [call.args[0] for call in draw_text.call_args_list])

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

    def prepare_enemy(self, path_progress: float = 34.0) -> None:
        """Seed an armored enemy near a tower using a separate core fixture."""
        enemy = create_enemy("armored")
        enemy.id = 90
        enemy.path_progress = path_progress
        enemy.apply_slow(2.0)
        self.gui.game = GameState(create_demo_map(), enemies=[enemy])
        self.gui.game.build("gun_tower", Position(27, 0))

    def click_enemy(self) -> None:
        """Click the rendered position rather than the containing cell's center."""
        snapshot = self.gui.game.snapshot()
        enemy = next(
            enemy for row in snapshot.board for cell in row for enemy in cell.enemies
            if enemy.id == 90
        )
        self.gui._handle_board_click(self.gui.board._world_point(enemy.world_position, snapshot))

    def test_enemy_details_follow_runtime_id_across_cells(self) -> None:
        self.prepare_enemy(path_progress=0.0)
        self.click_enemy()
        enemy = self.gui._selected_enemy(self.gui.game.snapshot())
        lines = "\n".join(Sidebar.enemy_inspection_lines(enemy))
        for label in ("Armor 2", "Base speed", "Slowed: YES", "Kill reward", "Core damage"):
            self.assertIn(label, lines)
        self.gui.game.start_next_wave()
        self.gui.game.step(1.0)
        self.gui._refresh_selection(self.gui.game.snapshot())
        moved = self.gui._selected_enemy(self.gui.game.snapshot())
        self.assertEqual(moved.id, enemy.id)
        self.assertNotEqual(moved.position, enemy.position)
        self.assertIsNone(self.gui.selected_building_id)

    def test_select_tower_set_target_and_clear_target(self) -> None:
        self.prepare_enemy()
        self.click_cell(Position(27, 0))
        tower_id = self.gui.selected_building_id
        self.gui._handle_button(self.gui.sidebar.target_button)
        self.assertTrue(self.gui.targeting_mode)
        self.click_enemy()
        selected = self.gui._selected_tower(self.gui.game.snapshot())
        self.assertEqual(selected.id, tower_id)
        self.assertEqual(selected.target_enemy_id, 90)
        self.assertFalse(self.gui.targeting_mode)
        self.assertIn("Manual target: #90", Sidebar.inspection_lines(
            self.gui.game.snapshot(), selected.position,
        ))
        self.gui._handle_button(self.gui.sidebar.clear_target_button)
        self.assertIsNone(self.gui._selected_tower(self.gui.game.snapshot()).target_enemy_id)

    def test_non_enemy_click_keeps_target_mode_and_escape_cancels(self) -> None:
        self.prepare_enemy()
        self.click_cell(Position(27, 0))
        self.gui._begin_targeting()
        self.click_cell(Position(0, 0))
        self.assertTrue(self.gui.targeting_mode)
        self.gui._cancel_build()
        self.assertFalse(self.gui.targeting_mode)
        self.assertIsNotNone(self.gui._selected_tower(self.gui.game.snapshot()))

    def test_target_rejection_is_visible_and_can_be_retried(self) -> None:
        self.prepare_enemy()
        self.click_cell(Position(27, 0))
        self.gui._begin_targeting()
        with patch.object(self.gui.game, "set_tower_target", side_effect=ValueError("Enemy not found.")):
            self.click_enemy()
        self.assertEqual(self.gui.message, "Enemy not found.")
        self.assertTrue(self.gui.targeting_mode)
        self.click_enemy()
        self.assertFalse(self.gui.targeting_mode)

    def test_core_fallback_clears_manual_target_in_gui_snapshot(self) -> None:
        self.prepare_enemy(path_progress=0.0)
        self.click_cell(Position(27, 0))
        self.gui._begin_targeting()
        self.click_enemy()
        self.gui.game.start_next_wave()
        self.gui._advance_once(0.05)
        selected = self.gui._selected_tower(self.gui.game.snapshot())
        self.assertIsNone(selected.target_enemy_id)
        self.assertIn("Manual target: Auto", Sidebar.inspection_lines(
            self.gui.game.snapshot(), selected.position,
        ))

    def test_removed_enemy_selection_is_cleared(self) -> None:
        self.prepare_enemy(path_progress=35.0)
        self.click_enemy()
        self.gui.game.start_next_wave()
        self.gui.game.step(30.0)
        self.gui._refresh_selection(self.gui.game.snapshot())
        self.assertIsNone(self.gui.selected_enemy_id)

    def test_enemy_picking_and_rendering_use_same_crowded_marker_positions(self) -> None:
        enemies = []
        for enemy_id in (90, 91):
            enemy = create_enemy("basic")
            enemy.id = enemy_id
            enemy.path_progress = 10.0
            enemies.append(enemy)
        self.gui.game = GameState(create_demo_map(), enemies=enemies)
        snapshot = self.gui.game.snapshot()
        for enemy, center in self.gui.board._enemy_markers(snapshot):
            self.assertEqual(self.gui.board.enemy_at(center, snapshot).id, enemy.id)
        self.assertIsNone(self.gui.board.enemy_at((0, 0), snapshot))

    def test_targeting_controls_render_with_manual_target(self) -> None:
        self.prepare_enemy()
        self.click_cell(Position(27, 0))
        self.gui._begin_targeting()
        self.click_enemy()
        self.gui.run(max_frames=2)

    def test_speed_buttons_scale_elapsed_time_with_fixed_logic_steps(self) -> None:
        for button, multiplier in self.gui.sidebar.speed_buttons.items():
            with self.subTest(multiplier=multiplier):
                self.gui.game = GameState(create_demo_map())
                self.gui._handle_button(self.gui.sidebar.run_button)
                self.gui._handle_button(button)
                self.gui._update_simulation(0.2)
                self.assertAlmostEqual(
                    self.gui.game.snapshot().status.elapsed_seconds, 0.2 * multiplier,
                )

    def test_build_bullet_time_resumes_preferred_speed_after_cancel(self) -> None:
        self.gui._handle_button(self.gui.sidebar.run_button)
        self.gui._set_speed(2.0)
        build_button = next(
            button for button, kind in self.gui.sidebar.build_buttons.items() if kind == "power_node"
        )
        self.gui._handle_button(build_button)
        self.assertEqual(self.gui._effective_speed(self.gui.game.snapshot()), 0.25)
        self.gui._update_simulation(0.4)
        self.assertAlmostEqual(self.gui.game.snapshot().status.elapsed_seconds, 0.1)
        self.gui._cancel_build()
        self.assertEqual(self.gui._effective_speed(self.gui.game.snapshot()), 2.0)
        self.gui._update_simulation(0.1)
        self.assertAlmostEqual(self.gui.game.snapshot().status.elapsed_seconds, 0.3)

    def test_repair_focus_bullet_time_ends_after_successful_repair(self) -> None:
        plant = PowerPlant(50, Position(30, 6))
        plant.take_damage(1)
        self.gui.game = GameState(create_demo_map(), buildings=[plant])
        self.gui._set_speed(2.0)
        self.gui._handle_button(self.gui.sidebar.run_button)
        self.click_cell(plant.position)
        self.gui._update_simulation(0.2)
        self.assertAlmostEqual(self.gui.game.snapshot().status.elapsed_seconds, 0.05)
        self.gui._repair_selected_building()
        self.assertEqual(self.gui._effective_speed(self.gui.game.snapshot()), 2.0)

    def test_pause_and_day_never_accumulate_catch_up_time(self) -> None:
        self.gui._set_speed(2.0)
        self.gui._update_simulation(5.0)
        self.assertEqual(self.gui.game.snapshot().status.elapsed_seconds, 0.0)
        self.gui._handle_button(self.gui.sidebar.run_button)
        self.gui._handle_button(self.gui.sidebar.run_button)
        self.gui._update_simulation(5.0)
        self.assertEqual(self.gui.simulation_accumulator, 0.0)
        self.gui._handle_button(self.gui.sidebar.run_button)
        self.gui._update_simulation(0.1)
        self.assertAlmostEqual(self.gui.game.snapshot().status.elapsed_seconds, 0.2)

    def test_step_pauses_and_advances_one_logical_second_at_any_speed(self) -> None:
        self.gui._handle_button(self.gui.sidebar.run_button)
        self.gui._set_speed(2.0)
        self.gui._handle_button(self.gui.sidebar.step_button)
        self.assertAlmostEqual(self.gui.game.snapshot().status.elapsed_seconds, 1.0)
        self.assertFalse(self.gui.running)
        self.gui._update_simulation(1.0)
        self.assertAlmostEqual(self.gui.game.snapshot().status.elapsed_seconds, 1.0)

    def test_wave_settlement_returns_to_day_without_starting_another_night(self) -> None:
        self.gui._handle_button(self.gui.sidebar.run_button)
        self.gui._set_speed(2.0)
        for _ in range(400):
            self.gui._update_simulation(0.25)
            if self.gui.game.snapshot().status.phase != GamePhase.NIGHT:
                break
        snapshot = self.gui.game.snapshot()
        self.assertEqual(snapshot.status.phase, GamePhase.DAY)
        self.assertEqual(snapshot.status.wave_index, 1)
        self.assertFalse(self.gui.running)
        self.assertEqual(self.gui.simulation_accumulator, 0.0)
        self.gui._update_simulation(10.0)
        self.assertEqual(self.gui.game.snapshot(), snapshot)

    def test_defeat_stops_time_and_rejects_building_actions(self) -> None:
        enemy = create_enemy("basic")
        enemy.id = 90
        enemy.path_progress = 35.0
        self.gui.game = GameState(create_demo_map(), core_hp=1, enemies=[enemy])
        self.click_cell(Position(30, 3))
        self.gui._handle_button(self.gui.sidebar.run_button)
        self.gui._update_simulation(5.0)
        snapshot = self.gui.game.snapshot()
        self.assertEqual(snapshot.status.phase, GamePhase.DEFEAT)
        self.assertFalse(self.gui.running)
        for action in (self.gui._sell_selected_building, self.gui._repair_selected_building):
            action()
            self.assertEqual(self.gui.game.snapshot(), snapshot)
            self.assertEqual(self.gui.message, snapshot.status.result_message)

    def test_bullet_time_status_renders(self) -> None:
        self.gui._handle_button(self.gui.sidebar.run_button)
        self.gui.selected_kind = "power_node"
        self.gui.run(max_frames=2)


if __name__ == "__main__":
    unittest.main()
