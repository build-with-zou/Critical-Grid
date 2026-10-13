"""Pygame GUI for the current Critical Grid prototype.

Run from the project root with ``python gui/gui.py``. Requires pygame-ce and
pygame_gui. The board is a read-only view of GameState except for calls to its
public build/step/wave/demolish methods.
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

from grid_td.buildings import Building, Core, Tower
from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position
from gui.board_view import BoardView
from gui.styles import (
    BACKGROUND,
    BUILD_KINDS,
    FPS,
    MUTED,
    PANEL,
    PANEL_LEFT,
    TEXT,
    WINDOW_SIZE,
)


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
        self.running = False
        self.selected_kind: str | None = None
        self.selected_tower_id: int | None = None
        self.inspected_position: Position | None = None
        self.simulation_accumulator = 0.0
        self.message = "Click the map to inspect. Choose a building button before placing."
        self.build_buttons: dict[UIButton, str] = {}
        self._create_controls()
        self._update_build_button_labels()

    def _create_controls(self) -> None:
        for index, (kind, label, _, _) in enumerate(BUILD_KINDS):
            col, row = index % 2, index // 2
            button = UIButton(
                pygame.Rect(PANEL_LEFT + 16 + col * 164, 175 + row * 52, 151, 42),
                label,
                self.manager,
            )
            self.build_buttons[button] = kind

        self.run_button = UIButton(
            pygame.Rect(PANEL_LEFT + 16, 355, 151, 44), "Run", self.manager
        )
        self.step_button = UIButton(
            pygame.Rect(PANEL_LEFT + 180, 355, 151, 44), "Step +1s", self.manager
        )
        self.cancel_build_button = UIButton(
            pygame.Rect(PANEL_LEFT + 16, 410, 151, 42), "Cancel Build", self.manager,
        )
        self.demolish_button = UIButton(
            pygame.Rect(PANEL_LEFT + 180, 410, 151, 42), "Demolish Tower", self.manager,
        )

    def _update_build_button_labels(self) -> None:
        labels = {kind: label for kind, label, _, _ in BUILD_KINDS}
        for button, kind in self.build_buttons.items():
            marker = "> " if kind == self.selected_kind else "  "
            button.set_text(marker + labels[kind])

    def _handle_button(self, button: UIButton) -> None:
        if button in self.build_buttons:
            if self.game.is_finished:
                self.message = self.game.result_message
                return
            chosen_kind = self.build_buttons[button]
            self.selected_kind = None if self.selected_kind == chosen_kind else chosen_kind
            self.selected_tower_id = None
            self._update_build_button_labels()
            if self.selected_kind is None:
                self.message = "Build cancelled. Click the map to inspect."
            else:
                self.message = f"Build mode: {self.selected_kind.replace('_', ' ')}. Click a map cell."
        elif button == self.run_button:
            if self.game.is_finished:
                self.message = self.game.result_message
                return
            self.running = not self.running
            self.simulation_accumulator = 0.0
            if not self.running:
                self.board.finish_animation()
            self.run_button.set_text("Pause" if self.running else "Run")
            self.message = "Simulation running." if self.running else "Simulation paused."
        elif button == self.step_button:
            self._advance_once(animate=True)
        elif button == self.cancel_build_button:
            self._cancel_build()
        elif button == self.demolish_button:
            self._demolish_selected_tower()

    def _cancel_build(self) -> None:
        self.selected_kind = None
        self._update_build_button_labels()
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
                self.message = f"{building_at_position.name} at ({position.x}, {position.y}) selected."
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
            self.selected_kind = None
            self._update_build_button_labels()

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
            self.message = f"Demolished {tower.name} at ({tower.position.x}, {tower.position.y}). No refund."
        self.selected_tower_id = None

    def _advance_once(self, *, animate: bool = False) -> None:
        if self.game.is_finished:
            self.message = self.game.result_message
            return
        before = self.board.capture_progress()
        self.game.step(1.0)
        self.board.complete_step(before, animate=animate)
        if self.game.waiting_for_next_wave:
            self.message = self.game.end_wave()
            if not self.game.is_finished:
                self.game.start_next_wave()
        if self.game.is_finished:
            self.running = False
            self.board.finish_animation()
            self.run_button.set_text("Run")
            self.message = self.game.result_message

    def _text(self, value: str, x: int, y: int, *, color=TEXT, font=None) -> None:
        surface = (font or self.font).render(value, True, color)
        self.screen.blit(surface, (x, y))

    def _draw_status(self) -> None:
        report = self.game.latest_power_report
        pygame.draw.rect(self.screen, PANEL, pygame.Rect(18, 16, 1044, 96), border_radius=8)
        self._text("CRITICAL GRID", 34, 25, font=self.title_font)
        self._text(
            f"{self.game.current_wave_name}   Time {self.game.elapsed_seconds}s"
            f"   {'RUNNING' if self.running else 'PAUSED'}",
            339, 32, color=MUTED,
        )
        self._text(
            f"Gold {self.game.gold}    Debt {self.game.debt}    Core HP {self.game.core_hp}"
            f"    Power {report.total_supply}/{report.total_demand}"
            f"    Efficiency {report.efficiency:.0%}",
            34, 76, font=self.small_font,
        )

    def _inspection_lines(self) -> tuple[str, str, str]:
        position = self.inspected_position
        if position is None:
            return (
                "Click a tile to inspect its terrain.",
                "Click a building to inspect its status.",
                "Choose a button above to enter build mode.",
            )

        building: Building | None = self.game.building_at(position)
        coordinate = f"({position.x}, {position.y})"
        if building is not None:
            current_hp = self.game.core_hp if isinstance(building, Core) else building.hp
            grid_status = "Connected" if building.connected_to_grid else "Disconnected"
            if isinstance(building, Tower):
                detail = f"Range {building.range}  Damage {building.damage:g}  Cooldown {building.cooldown_seconds:g}s"
            else:
                detail = f"Supply {building.power_supply}  Demand {building.power_draw}  Cost {building.cost}"
            return (
                f"{coordinate}  {building.name}  HP {current_hp}/{building.max_hp}",
                f"Grid {grid_status}  Efficiency {building.efficiency:.0%}",
                detail,
            )

        grid_map = self.game.grid_map
        if grid_map.is_route(position):
            terrain, note = "Route", "Enemy path; construction prohibited."
        elif grid_map.is_mine_site(position):
            terrain, note = "Mine site", "Only mines can be built here."
        elif grid_map.is_high_ground(position):
            terrain, note = "High ground", "Defense towers gain +1 range."
        else:
            terrain, note = "Ground", "Standard building terrain."
        buildable = "Yes" if grid_map.is_buildable(position) else "No"
        return (
            f"{coordinate}  Terrain: {terrain}",
            f"Buildable: {buildable}",
            note,
        )

    def _draw_panel(self) -> None:
        pygame.draw.rect(self.screen, PANEL, pygame.Rect(PANEL_LEFT, 132, 347, 424), border_radius=7)
        self._text("BUILD", PANEL_LEFT + 16, 143)
        if self.selected_kind is None:
            self._text("INSPECT MODE", PANEL_LEFT + 16, 462,
                       color=(111, 214, 228), font=self.small_font)
        else:
            self._text(f"BUILD MODE: {self.selected_kind.replace('_', ' ').upper()}",
                       PANEL_LEFT + 16, 462, color=(245, 225, 164), font=self.small_font)
        for index, line in enumerate(self._inspection_lines()):
            self._text(line, PANEL_LEFT + 16, 485 + index * 22,
                       color=MUTED, font=self.small_font)
        self._text("$ mine site    ^ high ground    colored dots: enemies", 35, 530,
                   color=MUTED, font=self.small_font)

    def _draw_message(self) -> None:
        pygame.draw.rect(self.screen, PANEL, pygame.Rect(18, 568, 1044, 76), border_radius=8)
        self._text("EVENT", 34, 579, color=MUTED, font=self.small_font)
        words = self.message.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and self.small_font.size(candidate)[0] > 1000:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        for index, line in enumerate(lines[:2]):
            self._text(line, 34, 602 + index * 22, font=self.small_font)

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
                self._draw_status()
                self.board.draw(
                    self.selected_tower_id,
                    self.inspected_position,
                    show_hover=not self.game.is_finished,
                )
                self._draw_panel()
                self._draw_message()
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
