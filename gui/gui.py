"""Pygame GUI for the current Critical Grid spatial and phase contracts.

Run from the project root with ``python gui/gui.py``. Requires pygame-ce and
pygame_gui. Gameplay changes go through GameState commands; drawing uses its
immutable snapshot.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pygame
import pygame_gui
from pygame_gui.elements import UIButton

# Running this file directly places gui/ on sys.path, not the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from grid_td.game_state import BuildingSnapshot, GamePhase, GameSnapshot, GameState
from grid_td.map import create_demo_map
from grid_td.position import Position
from gui.board_view import BoardView
from gui.hud import HUD
from gui.menu import MenuView
from gui.sidebar import Sidebar
from gui.styles import BACKGROUND, FPS, WINDOW_SIZE


LOGIC_STEP = 0.05


class CriticalGridGUI:
    """Own window and input state while GameState owns the simulation."""

    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption("Critical Grid")
        self.screen = pygame.display.set_mode(WINDOW_SIZE)
        self.clock = pygame.time.Clock()
        self.manager = pygame_gui.UIManager(WINDOW_SIZE)
        self.font = pygame.font.SysFont("arial", 21)
        self.small_font = pygame.font.SysFont("arial", 17)
        self.title_font = pygame.font.SysFont("arial", 30, bold=True)

        self.game = GameState(create_demo_map())
        self.board = BoardView(self.screen, self.font)
        self.sidebar = Sidebar(self.screen, self.manager, self.small_font, self.font)
        self.hud = HUD(self.screen, self.font, self.small_font, self.title_font)
        self.menu = MenuView(self.screen)
        self.view = "start"
        self.running = False
        self.selected_kind: str | None = None
        self.selected_building_id: int | None = None
        self.inspected_position: Position | None = None
        self.simulation_accumulator = 0.0
        self.message = "Plan your grid. Select a building, then click a small-cell anchor."
        self.sidebar.set_phase(GamePhase.DAY, self.running)

    def _handle_menu_action(self, action: str | None) -> None:
        """Move between the title, level selection, and playable game screens."""
        if self.view == "start" and action == "enter":
            self.view = "levels"
        elif self.view == "levels" and action == "back":
            self.view = "start"
        elif self.view == "levels" and action == "play":
            self.view = "game"

    def _handle_button(self, button: UIButton) -> None:
        """Dispatch commands through GameState and reflect phase changes."""
        status = self.game.snapshot().status
        if button in self.sidebar.build_buttons:
            if status.is_finished:
                self.message = status.result_message
                return
            kind = self.sidebar.build_buttons[button]
            self.selected_kind = None if self.selected_kind == kind else kind
            self.selected_building_id = None
            self.inspected_position = None
            self.sidebar.update_build_selection(self.selected_kind)
            self.message = (
                f"Choose an anchor for {self.selected_kind.replace('_', ' ')}."
                if self.selected_kind else "Build cancelled. Click the map to inspect."
            )
        elif button == self.sidebar.run_button:
            if status.is_finished:
                self.message = status.result_message
            elif status.phase == GamePhase.DAY:
                try:
                    self.game.start_next_wave()
                except ValueError as error:
                    self.message = str(error)
                else:
                    self.running = True
                    self.simulation_accumulator = 0.0
                    self.message = "Night started. Defend the core."
            else:
                self.running = not self.running
                self.simulation_accumulator = 0.0
                self.message = "Simulation running." if self.running else "Simulation paused."
            self.sidebar.set_phase(self.game.snapshot().status.phase, self.running)
        elif button == self.sidebar.step_button:
            if status.phase != GamePhase.NIGHT:
                self.message = (
                    status.result_message if status.is_finished
                    else "Start Night before stepping the simulation."
                )
            else:
                for _ in range(round(1.0 / LOGIC_STEP)):
                    if self.game.snapshot().status.phase != GamePhase.NIGHT:
                        break
                    self._advance_once(LOGIC_STEP)
        elif button == self.sidebar.cancel_build_button:
            self._cancel_build()
        elif button == self.sidebar.sell_button:
            self._sell_selected_building()
        elif button == self.sidebar.repair_button:
            self._repair_selected_building()
        elif button == self.sidebar.overload_button:
            self._overload_selected_tower()
        elif button == self.sidebar.intel_button:
            self._buy_wave_intel()
        elif button == self.sidebar.overdraft_button:
            self._take_core_overdraft()

    def _buy_wave_intel(self) -> None:
        """Buy the core's current-wave briefing and report the actual charge."""
        self._cancel_build()
        before = self.game.snapshot().status
        try:
            briefing = self.game.buy_wave_intel()
        except ValueError as error:
            self.message = str(error)
        else:
            spent = before.gold - self.game.snapshot().status.gold
            self.message = f"Wave intel (-{spent} gold): {briefing}" if spent else briefing

    def _take_core_overdraft(self) -> None:
        """Apply the default core overdraft and report its resource changes."""
        self._cancel_build()
        before = self.game.snapshot().status
        try:
            self.game.core_overdraft()
        except ValueError as error:
            self.message = str(error)
        else:
            after = self.game.snapshot().status
            self.message = (
                f"Core overdraft: +{after.gold - before.gold} gold, "
                f"+{after.debt - before.debt} debt."
            )

    def _cancel_build(self) -> None:
        """Leave construction mode without changing the inspected cell."""
        self.selected_kind = None
        self.sidebar.update_build_selection(None)
        self.message = "Build cancelled. Click the map to inspect."

    def _handle_board_click(self, mouse_pos: tuple[int, int]) -> None:
        """Inspect an occupied small cell or build from its top-left anchor."""
        snapshot = self.game.snapshot()
        position = self.board.position_at(mouse_pos, snapshot)
        if position is None:
            return
        self.inspected_position = position
        building = snapshot.board[position.y][position.x].building
        if self.selected_kind is None:
            self.selected_building_id = building.id if building is not None else None
            if building is None:
                self.message = f"Terrain at ({position.x}, {position.y}) selected."
            else:
                self.message = f"{building.name} at ({position.x}, {position.y}) selected."
                if building.range is not None:
                    if not building.connected_to_grid:
                        self.message += " Connect this tower to the core."
                    elif building.efficiency <= 0:
                        self.message += " This tower needs power."
                    else:
                        self.message += " Highlighted cells are in range. O: overload."
            return
        if snapshot.status.is_finished:
            self.message = snapshot.status.result_message
            return
        self.selected_building_id = None
        try:
            # The core rechecks the full footprint even after a valid hover preview.
            self.game.build(self.selected_kind, position)
        except ValueError as error:
            self.message = f"Build failed: {error}"
        else:
            placed = self.game.snapshot().board[position.y][position.x].building
            assert placed is not None
            self.selected_building_id = placed.id
            self.message = f"Built {placed.name} at ({position.x}, {position.y})."
            if placed.range is not None:
                if not placed.connected_to_grid:
                    self.message += " Connect it to the core before it can attack."
            self.selected_kind = None
            self.sidebar.update_build_selection(None)

    def _selected_building(self, snapshot: GameSnapshot) -> BuildingSnapshot | None:
        """Resolve a selected ID from the current snapshot after core changes."""
        for row in snapshot.board:
            for cell in row:
                building = cell.building
                if (
                    building is not None and building.id == self.selected_building_id
                ):
                    return building
        return None

    def _selected_tower(self, snapshot: GameSnapshot) -> BuildingSnapshot | None:
        """Restrict tower-only commands without limiting building selection."""
        building = self._selected_building(snapshot)
        return building if building is not None and building.range is not None else None

    def _sell_selected_building(self) -> None:
        """Sell any selected non-core building and report the core's actual refund."""
        snapshot = self.game.snapshot()
        if snapshot.status.is_finished:
            self.message = snapshot.status.result_message
            return
        building = self._selected_building(snapshot)
        if building is None:
            self.message = "Select a building first, then press Sell Building."
            return
        try:
            refund = self.game.sell_building(building.id)
        except ValueError as error:
            self.message = str(error)
        else:
            self.message = f"Sold {building.name}. Refund +{refund} gold."
            self.selected_building_id = None

    def _repair_selected_building(self) -> None:
        """Restore selected building HP through the core, separately from service fees."""
        snapshot = self.game.snapshot()
        if snapshot.status.is_finished:
            self.message = snapshot.status.result_message
            return
        building = self._selected_building(snapshot)
        if building is None:
            self.message = "Select a damaged building first, then press Repair HP."
            return
        try:
            cost = self.game.repair_building(building.id)
        except ValueError as error:
            self.message = str(error)
        else:
            self.message = f"Repaired {building.name} to full HP. Spent {cost} gold."

    def _overload_selected_tower(self) -> None:
        """Overload the selected tower while keeping display data immutable."""
        snapshot = self.game.snapshot()
        if snapshot.status.is_finished:
            self.message = snapshot.status.result_message
            return
        tower = self._selected_tower(snapshot)
        if tower is None:
            self.message = "Click an existing tower first, then press O to overload."
            return
        try:
            self.game.overload_tower(tower.id)
        except ValueError as error:
            self.message = str(error)
        else:
            debt_added = self.game.snapshot().status.debt - snapshot.status.debt
            self.message = f"{tower.name} overloaded. Debt +{debt_added}; settlement service fee due."

    def _advance_once(self, seconds: float) -> None:
        """Advance one short core step and return to planning after settlement."""
        status = self.game.snapshot().status
        if status.is_finished or status.phase != GamePhase.NIGHT:
            self.running = False
            self.sidebar.set_phase(status.phase, False)
            return
        self.game.step(seconds)
        status = self.game.snapshot().status
        if status.waiting_for_next_wave:
            self.message = self.game.end_wave()
            self.running = False
            self.simulation_accumulator = 0.0
        status = self.game.snapshot().status
        if status.is_finished:
            self.running = False
            self.simulation_accumulator = 0.0
            self.message = status.result_message
        if status.phase != GamePhase.NIGHT:
            self.sidebar.set_phase(status.phase, self.running)

    def run(self, max_frames: int | None = None) -> None:
        """Run input, fixed logical steps, and rendering; cap frames for smoke checks."""
        frames = 0
        try:
            active = True
            while active:
                dt = min(self.clock.tick(FPS) / 1000.0, 0.25)
                for event in pygame.event.get():
                    was_game = self.view == "game"
                    if event.type == pygame.QUIT:
                        active = False
                    elif not was_game:
                        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                            self._handle_menu_action(self.menu.action_at(self.view, event.pos))
                        elif event.type == pygame.KEYDOWN:
                            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                                self._handle_menu_action(
                                    "enter" if self.view == "start" else "play"
                                )
                            elif event.key == pygame.K_ESCAPE and self.view == "levels":
                                self._handle_menu_action("back")
                    elif event.type == pygame_gui.UI_BUTTON_PRESSED:
                        self._handle_button(event.ui_element)
                    elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        self._handle_board_click(event.pos)
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_DELETE:
                        self._sell_selected_building()
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                        self._repair_selected_building()
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_o:
                        self._overload_selected_tower()
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        self._cancel_build()
                    if was_game:
                        self.manager.process_events(event)

                if self.view == "game" and self.running:
                    self.simulation_accumulator += dt
                    while self.simulation_accumulator + 1e-9 >= LOGIC_STEP and self.running:
                        self.simulation_accumulator -= LOGIC_STEP
                        self._advance_once(LOGIC_STEP)

                if self.view == "game":
                    snapshot = self.game.snapshot()
                    self.sidebar.update_actions(snapshot, self._selected_building(snapshot))
                    hover = (
                        self.board.position_at(pygame.mouse.get_pos(), snapshot)
                        if not snapshot.status.is_finished else None
                    )
                    preview = None
                    display_message = self.message
                    if self.selected_kind is not None and hover is not None:
                        preview = self.game.preview_build(self.selected_kind, hover)
                        display_message = (
                            f"Click to place {self.selected_kind.replace('_', ' ')}."
                            if preview.is_valid else f"Cannot place: {preview.reason}"
                        )
                    self.manager.update(dt)
                    self.screen.fill(BACKGROUND)
                    self.hud.draw_status(snapshot, self.running)
                    self.board.draw(
                        snapshot, self.selected_building_id,
                        self.inspected_position, hover, preview,
                    )
                    self.sidebar.draw(snapshot, self.selected_kind, self.inspected_position)
                    self.hud.draw_message(display_message)
                    self.manager.draw_ui(self.screen)
                else:
                    self.menu.draw(self.view, pygame.mouse.get_pos())
                pygame.display.flip()
                frames += 1
                if max_frames is not None and frames >= max_frames:
                    active = False
        finally:
            pygame.quit()


def main() -> None:
    CriticalGridGUI().run()


if __name__ == "__main__":
    main()
