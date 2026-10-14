"""Build controls and contextual terrain/building information."""

from __future__ import annotations

import pygame
import pygame_gui
from pygame_gui.elements import UIButton

from grid_td.buildings import Building, Core, Tower
from grid_td.game_state import GameState
from grid_td.position import Position
from gui.styles import BUILD_KINDS, MUTED, PANEL, PANEL_LEFT


class Sidebar:
    """Own pygame_gui buttons and draw the current inspection panel."""

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
                pygame.Rect(PANEL_LEFT + 16 + col * 164, 175 + row * 52, 151, 42),
                label,
                manager,
            )
            self.build_buttons[button] = kind

        self.run_button = UIButton(
            pygame.Rect(PANEL_LEFT + 16, 355, 151, 44), "Run", manager
        )
        self.step_button = UIButton(
            pygame.Rect(PANEL_LEFT + 180, 355, 151, 44), "Step +1s", manager
        )
        self.cancel_build_button = UIButton(
            pygame.Rect(PANEL_LEFT + 16, 410, 151, 42), "Cancel Build", manager
        )
        self.demolish_button = UIButton(
            pygame.Rect(PANEL_LEFT + 180, 410, 151, 42), "Demolish Tower", manager
        )
        self.update_build_selection(None)

    def update_build_selection(self, selected_kind: str | None) -> None:
        labels = {kind: label for kind, label, _, _ in BUILD_KINDS}
        for button, kind in self.build_buttons.items():
            marker = "> " if kind == selected_kind else "  "
            button.set_text(marker + labels[kind])

    def set_running(self, running: bool) -> None:
        self.run_button.set_text("Pause" if running else "Run")

    def draw(
        self,
        game: GameState,
        selected_kind: str | None,
        inspected_position: Position | None,
    ) -> None:
        pygame.draw.rect(
            self.screen, PANEL, pygame.Rect(PANEL_LEFT, 132, 347, 424), border_radius=7
        )
        self._text("BUILD", PANEL_LEFT + 16, 143, (232, 239, 244), self.heading_font)
        if selected_kind is None:
            self._text("INSPECT MODE", PANEL_LEFT + 16, 462, (111, 214, 228))
        else:
            label = f"BUILD MODE: {selected_kind.replace('_', ' ').upper()}"
            self._text(label, PANEL_LEFT + 16, 462, (245, 225, 164))
        for index, line in enumerate(self.inspection_lines(game, inspected_position)):
            self._text(line, PANEL_LEFT + 16, 485 + index * 22, MUTED)
        self._text(
            "$ mine site    ^ high ground    dots: enemies    O: overload tower",
            35, 530, MUTED,
        )

    @staticmethod
    def inspection_lines(
        game: GameState, position: Position | None
    ) -> tuple[str, str, str]:
        if position is None:
            return (
                "Click a tile to inspect its terrain.",
                "Click a building to inspect its status.",
                "Choose a button above to enter build mode.",
            )

        building: Building | None = game.building_at(position)
        coordinate = f"({position.x}, {position.y})"
        if building is not None:
            current_hp = game.core_hp if isinstance(building, Core) else building.hp
            grid_status = "Connected" if building.connected_to_grid else "Disconnected"
            if isinstance(building, Tower):
                if not building.connected_to_grid:
                    detail = "Cannot attack: connect this tower to the core."
                elif building.efficiency <= 0:
                    detail = "Cannot attack: this tower needs power."
                else:
                    detail = (
                        f"Range {building.range}  Damage {building.current_damage():g}  "
                        f"Ready in {building.cooldown_remaining:.1f}s"
                    )
            else:
                detail = (
                    f"Supply {building.power_supply}  Demand {building.power_draw}  "
                    f"Cost {building.cost}"
                )
            return (
                f"{coordinate}  {building.name}  HP {current_hp}/{building.max_hp}",
                f"Grid {grid_status}  Efficiency {building.efficiency:.0%}",
                detail,
            )

        grid_map = game.grid_map
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

    def _text(
        self, value: str, x: int, y: int, color: tuple[int, int, int],
        font: pygame.font.Font | None = None,
    ) -> None:
        surface = (font or self.font).render(value, True, color)
        self.screen.blit(surface, (x, y))
