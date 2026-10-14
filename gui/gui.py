"""Pygame GUI for the current Critical Grid prototype.

Run from the project root with ``python gui/gui.py``. Requires pygame-ce and
pygame_gui. GameState owns combat; the GUI calls its public methods and shows
the results.
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

from grid_td.buildings import Tower
from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position
from gui.board_view import BoardView
from gui.hud import HUD
from gui.sidebar import Sidebar
from gui.styles import BACKGROUND, FPS, WINDOW_SIZE


class CriticalGridGUI:
    """Own the window and input state; let GameState own the game state."""

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
        self.board = BoardView(self.game, self.screen, self.font)
        self.sidebar = Sidebar(self.screen, self.manager, self.small_font, self.font)
        self.hud = HUD(self.screen, self.font, self.small_font, self.title_font)
        self.running = False
        self.selected_kind: str | None = None
        self.selected_tower_id: int | None = None
        self.inspected_position: Position | None = None
        self.simulation_accumulator = 0.0
        self.message = "Click the map to inspect. Choose a building button before placing."

    def _handle_button(self, button: UIButton) -> None:
        if button in self.sidebar.build_buttons:
            if self.game.is_finished:
                self.message = self.game.result_message
                return
            chosen_kind = self.sidebar.build_buttons[button]
            self.selected_kind = None if self.selected_kind == chosen_kind else chosen_kind
            self.selected_tower_id = None
            self.sidebar.update_build_selection(self.selected_kind)
            if self.selected_kind is None:
                self.message = "Build cancelled. Click the map to inspect."
            else:
                self.message = (
                    f"Build mode: {self.selected_kind.replace('_', ' ')}. "
                    "Click a map cell."
                )
        elif button == self.sidebar.run_button:
            if self.game.is_finished:
                self.message = self.game.result_message
                return
            self.running = not self.running
            self.simulation_accumulator = 0.0
            if not self.running:
                self.board.finish_animation()
            self.sidebar.set_running(self.running)
            self.message = "Simulation running." if self.running else "Simulation paused."
        elif button == self.sidebar.step_button:
            self._advance_once(animate=True)
        elif button == self.sidebar.cancel_build_button:
            self._cancel_build()
        elif button == self.sidebar.demolish_button:
            self._demolish_selected_tower()

    def _cancel_build(self) -> None:
        self.selected_kind = None
        self.sidebar.update_build_selection(None)
        self.message = "Build cancelled. Click the map to inspect."

    def _handle_board_click(self, mouse_pos: tuple[int, int]) -> None:
        position = self.board.position_at(mouse_pos)
        if position is None:
            return
        self.inspected_position = position
        building_at_position = self.game.building_at(position)
        if self.selected_kind is None:
            self.selected_tower_id = (
                building_at_position.id if isinstance(building_at_position, Tower) else None
            )
            if building_at_position is None:
                self.message = f"Terrain at ({position.x}, {position.y}) selected."
            else:
                self.message = (
                    f"{building_at_position.name} at "
                    f"({position.x}, {position.y}) selected."
                )
                if self.selected_tower_id is not None:
                    if not building_at_position.connected_to_grid:
                        self.message += " Disconnected towers cannot attack."
                    elif building_at_position.efficiency <= 0:
                        self.message += " This tower needs power to attack."
                    elif not self._tower_reaches_route(building_at_position):
                        self.message += " Its range does not reach the enemy path."
                    else:
                        self.message += " Highlighted path tiles are in range. O: overload."
            return
        if self.game.is_finished:
            self.message = self.game.result_message
            return
        self.selected_tower_id = None
        try:
            building = self.game.build(self.selected_kind, position)
        except ValueError as error:
            self.message = f"Build failed: {error}"
        else:
            self.message = f"Built {building.name} at ({position.x}, {position.y})."
            if isinstance(building, Tower):
                self.selected_tower_id = building.id
                if not building.connected_to_grid:
                    self.message += " Connect it to the core before it can attack."
                elif not self._tower_reaches_route(building):
                    self.message += " Its range does not reach the enemy path."
                else:
                    self.message += " Highlighted path tiles are in range."
            self.selected_kind = None
            self.sidebar.update_build_selection(None)

    def _tower_reaches_route(self, tower: Tower) -> bool:
        return any(
            tower.position.manhattan_distance(position) <= tower.range
            for position in self.game.grid_map.route
        )

    def _demolish_selected_tower(self) -> None:
        if self.game.is_finished:
            self.message = self.game.result_message
            return
        if self.selected_tower_id is None:
            self.message = "Click an existing tower first, then press Demolish."
            return
        try:
            tower = self.game.demolish_tower(self.selected_tower_id)
        except ValueError as error:
            self.message = str(error)
        else:
            self.message = (
                f"Demolished {tower.name} at "
                f"({tower.position.x}, {tower.position.y}). No refund."
            )
        self.selected_tower_id = None

    def _overload_selected_tower(self) -> None:
        if self.game.is_finished:
            self.message = self.game.result_message
            return
        if self.selected_tower_id is None:
            self.message = "Click an existing tower first, then press O to overload."
            return
        try:
            tower = self.game.find_tower(self.selected_tower_id)
            self.game.overload_tower(tower.id)
        except ValueError as error:
            self.selected_tower_id = None
            self.message = str(error)
        else:
            self.message = (
                f"{tower.name} overloaded for 8s. Debt +10; repair costs 5 gold "
                "at wave end."
            )

    def _advance_once(self, *, animate: bool = False) -> None:
        if self.game.is_finished:
            self.message = self.game.result_message
            return
        before = self.board.capture_progress()
        combat_before = self.board.capture_combat()
        self.game.step(1.0)
        self.board.complete_step(before, animate=animate)
        self.board.show_combat_results(combat_before, 1.0)
        if self.game.waiting_for_next_wave:
            self.message = self.game.end_wave()
            if not self.game.is_finished:
                self.game.start_next_wave()
        if self.game.is_finished:
            self.running = False
            self.board.finish_animation()
            self.sidebar.set_running(False)
            self.message = self.game.result_message

    def run(self, max_frames: int | None = None) -> None:
        """Start the event loop. max_frames is useful for a headless smoke check."""
        frames = 0
        try:
            active = True
            while active:
                dt = min(self.clock.tick(FPS) / 1000.0, 0.25)
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        active = False
                    elif event.type == pygame_gui.UI_BUTTON_PRESSED:
                        self._handle_button(event.ui_element)
                    elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        self._handle_board_click(event.pos)
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_DELETE:
                        self._demolish_selected_tower()
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_o:
                        self._overload_selected_tower()
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        self._cancel_build()
                    self.manager.process_events(event)

                if self.running:
                    self.simulation_accumulator += dt
                    while self.simulation_accumulator >= 1.0 and self.running:
                        self.simulation_accumulator -= 1.0
                        self._advance_once(animate=True)
                self.board.update(dt)

                self.manager.update(dt)
                self.screen.fill(BACKGROUND)
                self.hud.draw_status(self.game, self.running)
                self.board.draw(
                    self.selected_tower_id,
                    self.inspected_position,
                    show_hover=not self.game.is_finished,
                )
                self.sidebar.draw(self.game, self.selected_kind, self.inspected_position)
                self.hud.draw_message(self.message)
                self.manager.draw_ui(self.screen)
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
