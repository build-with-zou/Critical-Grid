"""Build controls and snapshot-based terrain and building details."""

from __future__ import annotations

import pygame
import pygame_gui
from pygame_gui.elements import UIButton

from grid_td.game_state import GamePhase, GameSnapshot
from grid_td.position import Position
from gui.styles import (
    BUILD_KINDS,
    CHARGED_COLOR,
    LIMITED_COLOR,
    MUTED,
    PANEL,
    PANEL_LEFT,
    UNCHARGED_COLOR,
)


class Sidebar:
    """Own action buttons and display the inspected small cell."""

    def __init__(
        self,
        screen: pygame.Surface,
        manager: pygame_gui.UIManager,
        font: pygame.font.Font,
        heading_font: pygame.font.Font,
    ) -> None:
        self.screen = screen
        self.font = font
        self.heading_font = heading_font
        self.build_buttons: dict[UIButton, str] = {}
        for index, (kind, label, _, _) in enumerate(BUILD_KINDS):
            col, row = index % 2, index // 2
            button = UIButton(
                pygame.Rect(PANEL_LEFT + 16 + col * 164, 170 + row * 46, 151, 40),
                label, manager,
            )
            self.build_buttons[button] = kind

        self.run_button = UIButton(
            pygame.Rect(PANEL_LEFT + 16, 312, 151, 40), "Start Night", manager
        )
        self.step_button = UIButton(
            pygame.Rect(PANEL_LEFT + 180, 312, 151, 40), "Step +1s", manager
        )
        self.cancel_build_button = UIButton(
            pygame.Rect(PANEL_LEFT + 16, 359, 151, 40), "Cancel Build", manager
        )
        self.demolish_button = UIButton(
            pygame.Rect(PANEL_LEFT + 180, 359, 151, 40), "Demolish Tower", manager
        )
        self.intel_button = UIButton(
            pygame.Rect(PANEL_LEFT + 16, 406, 151, 40), "Wave Intel (8g)", manager,
            tool_tip_text="Spend 8 gold to reveal the current wave briefing.",
        )
        self.overdraft_button = UIButton(
            pygame.Rect(PANEL_LEFT + 180, 406, 151, 40), "Overdraft +40g", manager,
            tool_tip_text="Gain 40 gold and add 54 debt. Each use adds more debt.",
        )
        self.update_build_selection(None)

    def update_build_selection(self, selected_kind: str | None) -> None:
        """Mark the active construction command on its button."""
        labels = {kind: label for kind, label, _, _ in BUILD_KINDS}
        for button, kind in self.build_buttons.items():
            marker = "> " if kind == selected_kind else "  "
            button.set_text(marker + labels[kind])

    def set_phase(self, phase: GamePhase, running: bool) -> None:
        """Name the main time-control action for the current core phase."""
        if phase == GamePhase.DAY:
            label = "Start Night"
        elif phase == GamePhase.NIGHT:
            label = "Pause" if running else "Run"
        else:
            label = "Finished"
        self.run_button.set_text(label)

    def draw(
        self,
        snapshot: GameSnapshot,
        selected_kind: str | None,
        inspected_position: Position | None,
    ) -> None:
        """Show selection mode and three concise lines from the snapshot."""
        pygame.draw.rect(
            self.screen, PANEL, pygame.Rect(PANEL_LEFT, 132, 347, 424), border_radius=7
        )
        self._text("BUILD", PANEL_LEFT + 16, 143, (232, 239, 244), self.heading_font)
        mode = (
            "INSPECT MODE" if selected_kind is None
            else f"BUILD MODE: {selected_kind.replace('_', ' ').upper()}"
        )
        self._text(
            mode, PANEL_LEFT + 16, 457,
            (111, 214, 228) if selected_kind is None else (245, 225, 164),
        )
        building = (
            snapshot.board[inspected_position.y][inspected_position.x].building
            if inspected_position is not None else None
        )
        for index, line in enumerate(self.inspection_lines(snapshot, inspected_position)):
            color = MUTED
            if index == 1 and building is not None:
                color = (
                    UNCHARGED_COLOR if not building.connected_to_grid
                    else LIMITED_COLOR if building.efficiency < 1
                    else CHARGED_COLOR
                )
            self._text(line, PANEL_LEFT + 16, 479 + index * 22, color)

    @staticmethod
    def inspection_lines(
        snapshot: GameSnapshot, position: Position | None
    ) -> tuple[str, str, str]:
        """Describe one cell without consulting mutable game entities."""
        if position is None:
            return (
                "Click a cell to inspect terrain.",
                "Click a building for its status.",
                "Choose a build button to place it.",
            )

        cell = snapshot.board[position.y][position.x]
        building = cell.building
        coordinate = f"({position.x}, {position.y})"
        if building is not None:
            hp = snapshot.status.core_hp if building.kind == "core" else building.hp
            grid = "CONNECTED" if building.connected_to_grid else "OFF GRID"
            if building.range is not None:
                if not building.connected_to_grid:
                    detail = "Connect to the core to attack."
                elif building.efficiency <= 0:
                    detail = "Needs power to attack."
                else:
                    detail = (
                        f"Range {building.range:g}  Base dmg {building.damage:g}"
                        f"  Ready {building.cooldown_remaining:.1f}s"
                    )
                if building.is_overloaded:
                    detail = (
                        f"OVERLOADED  Range {building.range:g}"
                        f"  Ready {building.cooldown_remaining:.1f}s"
                    )
            else:
                detail = (
                    f"Supply {building.power_supply}  Demand {building.power_draw}"
                    f"  Cost {building.cost}"
                )
            return (
                f"{coordinate}  {building.name}  HP {hp}/{building.max_hp}",
                f"Grid: {grid}  Output {building.efficiency:.0%}",
                detail,
            )

        terrain, note = {
            "route": ("Route", "Enemy road; no construction."),
            "mine_site": ("Mine site", "Only a full mine can fit here."),
            "high_ground": ("High ground", "Full tower footprint gains range."),
            "illegal": ("Blocked", "Construction prohibited."),
            "core": ("Core", "Reserved for the base core."),
        }.get(cell.terrain, ("Ground", "Standard building terrain."))
        return (
            f"{coordinate}  Terrain: {terrain}",
            f"Cell buildable: {'Yes' if cell.is_buildable else 'No'}",
            note,
        )

    def _text(
        self, value: str, x: int, y: int, color: tuple[int, int, int],
        font: pygame.font.Font | None = None,
    ) -> None:
        self.screen.blit((font or self.font).render(value, True, color), (x, y))
