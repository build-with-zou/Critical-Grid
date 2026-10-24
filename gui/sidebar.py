"""Build controls and snapshot-based terrain and building details."""

from __future__ import annotations

import pygame
import pygame_gui
from pygame_gui.elements import UIButton

from grid_td.game_state import BuildingSnapshot, EnemySnapshot, GamePhase, GameSnapshot, GameState
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
        """Keep construction, lifecycle commands, and details visible beside the map."""
        self.screen = screen
        self.font = font
        self.heading_font = heading_font
        self.build_buttons: dict[UIButton, str] = {}
        for index, (kind, label, _, _) in enumerate(BUILD_KINDS):
            col, row = index % 2, index // 2
            button = UIButton(
                pygame.Rect(PANEL_LEFT + 16 + col * 164, 170 + row * 40, 151, 36),
                label, manager,
            )
            self.build_buttons[button] = kind

        self.run_button = UIButton(
            pygame.Rect(PANEL_LEFT + 16, 294, 151, 36), "Start Night", manager
        )
        self.step_button = UIButton(
            pygame.Rect(PANEL_LEFT + 180, 294, 151, 36), "Step +1s", manager,
            tool_tip_text="Pause and advance one logical second, regardless of speed.",
        )
        self.cancel_build_button = UIButton(
            pygame.Rect(PANEL_LEFT + 16, 334, 151, 36), "Cancel Action", manager
        )
        self.sell_button = UIButton(
            pygame.Rect(PANEL_LEFT + 180, 334, 151, 36), "Sell Building", manager,
            tool_tip_text="Sell a non-core building for 70% of its cost. Shortcut: Delete.",
        )
        self.repair_button = UIButton(
            pygame.Rect(PANEL_LEFT + 16, 374, 151, 36), "Repair HP", manager,
            tool_tip_text="Restore full HP for 1 gold per missing HP. Shortcut: R.",
        )
        self.overload_button = UIButton(
            pygame.Rect(PANEL_LEFT + 180, 374, 151, 36), "Overload (O)", manager,
            tool_tip_text="Overload a tower for 8 logical seconds; adds debt and a service fee.",
        )
        self.target_button = UIButton(
            pygame.Rect(PANEL_LEFT + 16, 414, 151, 36), "Set Target (T)", manager,
            tool_tip_text="Select a tower, then click Set Target and an enemy. Escape cancels.",
        )
        self.clear_target_button = UIButton(
            pygame.Rect(PANEL_LEFT + 180, 414, 151, 36), "Clear Target", manager,
            tool_tip_text="Remove the manual target and resume automatic selection.",
        )
        self.intel_button = UIButton(
            pygame.Rect(PANEL_LEFT + 16, 454, 151, 36), "Wave Intel (8g)", manager,
            tool_tip_text="Spend 8 gold to reveal the current wave briefing.",
        )
        self.overdraft_button = UIButton(
            pygame.Rect(PANEL_LEFT + 180, 454, 151, 36), "Overdraft +40g", manager,
            tool_tip_text="Gain 40 gold and add 54 debt. Each use adds more debt.",
        )
        self.speed_buttons: dict[UIButton, float] = {}
        for index, multiplier in enumerate((0.5, 1.0, 2.0)):
            button = UIButton(
                pygame.Rect(PANEL_LEFT + 16 + index * 108, 494, 99, 32),
                f"{multiplier:g}x", manager,
                tool_tip_text=(
                    f"Speed {multiplier:g}x. Shortcut: {index + 1}. "
                    "Building placement or damaged-building inspection uses 0.25x bullet time."
                ),
            )
            self.speed_buttons[button] = multiplier
        self.update_build_selection(None)
        self.update_speed_selection(1.0)

    def update_speed_selection(self, selected_speed: float) -> None:
        """Mark the preferred speed, which resumes after automatic bullet time."""
        for button, multiplier in self.speed_buttons.items():
            marker = "> " if multiplier == selected_speed else ""
            button.set_text(f"{marker}{multiplier:g}x")

    def update_actions(
        self, snapshot: GameSnapshot, building: BuildingSnapshot | None,
        targeting: bool = False,
    ) -> None:
        """Show current prices and disable actions that cannot apply to the selection."""
        active = not snapshot.status.is_finished
        sellable = building is not None and building.kind != "core"
        repairable = building is not None and building.hp < building.max_hp
        tower = building is not None and building.range is not None
        refund = round(building.cost * GameState.SELL_REFUND_RATIO) if sellable else 0
        self.sell_button.set_text(f"Sell Building (+{refund}g)" if sellable else "Sell Building")
        self.repair_button.set_text(
            f"Repair HP ({building.repair_cost}g)" if building is not None else "Repair HP"
        )
        self.target_button.set_text("Click an Enemy..." if targeting else "Set Target (T)")
        for button, enabled in (
            (self.sell_button, active and sellable),
            (self.repair_button, active and repairable),
            (self.overload_button, active and tower),
            (self.target_button, active and tower),
            (self.clear_target_button, active and tower and building.target_enemy_id is not None),
            (self.run_button, active),
            (self.step_button, active and snapshot.status.phase == GamePhase.NIGHT),
            (self.intel_button, active),
            (self.overdraft_button, active),
        ):
            button.enable() if enabled else button.disable()
        for button in self.build_buttons:
            button.enable() if active else button.disable()

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
        selected_enemy: EnemySnapshot | None = None,
        targeting: bool = False,
    ) -> None:
        """Show selection mode, health, and separate electrical and condition output."""
        pygame.draw.rect(
            self.screen, PANEL, pygame.Rect(PANEL_LEFT, 132, 347, 600), border_radius=7
        )
        self._text("BUILD", PANEL_LEFT + 16, 143, (232, 239, 244), self.heading_font)
        mode = (
            "TARGET MODE: CLICK AN ENEMY" if targeting
            else "ENEMY DETAILS" if selected_enemy is not None
            else "INSPECT MODE" if selected_kind is None
            else f"BUILD MODE: {selected_kind.replace('_', ' ').upper()}"
        )
        self._text(
            mode, PANEL_LEFT + 16, 530,
            (111, 214, 228) if selected_kind is None else (245, 225, 164),
        )
        building = (
            snapshot.board[inspected_position.y][inspected_position.x].building
            if inspected_position is not None else None
        )
        lines = (
            self.enemy_inspection_lines(selected_enemy) if selected_enemy is not None
            else self.inspection_lines(snapshot, inspected_position)
        )
        for index, line in enumerate(lines):
            color = MUTED
            if index == 2 and building is not None:
                color = (
                    UNCHARGED_COLOR if not building.connected_to_grid
                    else LIMITED_COLOR if building.efficiency < 1
                    else CHARGED_COLOR
                )
            self._text(line, PANEL_LEFT + 16, 552 + index * 19, color)

    @staticmethod
    def inspection_lines(
        snapshot: GameSnapshot, position: Position | None
    ) -> tuple[str, ...]:
        """Describe snapshot condition and rated supply without inventing actual supply."""
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
            grid = "CONNECTED" if building.connected_to_grid else "OFF GRID"
            lines = (
                f"{building.name} #{building.id}  {coordinate}",
                f"HP {building.hp}/{building.max_hp}  Full repair: {building.repair_cost}g",
                f"Grid: {grid}  Power eff. {snapshot.status.power.efficiency:.0%}",
                f"Health eff. {building.health_efficiency:.0%}  Final eff. {building.efficiency:.0%}",
                f"Rated supply {building.power_supply}  Demand {building.power_draw}",
            )
            if building.range is not None:
                lines += (
                    f"Range {building.range:g}  Base damage {building.damage:g}",
                    f"Ready {building.cooldown_remaining:.1f}s  Overload: "
                    f"{'ON' if building.is_overloaded else 'OFF'}",
                    f"Manual target: #{building.target_enemy_id}" if building.target_enemy_id is not None
                    else "Manual target: Auto",
                )
            else:
                lines += ("Rated supply excludes damage losses.",)
            return lines + (
                "Overload service: due at settlement" if building.needs_repair
                else "Overload service: none due",
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

    @staticmethod
    def enemy_inspection_lines(enemy: EnemySnapshot) -> tuple[str, ...]:
        """Describe a moving enemy by ID; speed is the base value before slowing."""
        return (
            f"{enemy.name} #{enemy.id}",
            f"HP {enemy.hp:g}/{enemy.max_hp:g}  Armor {enemy.armor}",
            f"Base speed {enemy.speed:g} world units/s",
            f"Slowed: {'YES' if enemy.is_slowed else 'NO'}",
            f"Kill reward {enemy.reward}g  Core damage {enemy.damage_to_core}",
            f"Route progress {enemy.path_progress:.1f} world units",
            f"World ({enemy.world_position.x:.1f}, {enemy.world_position.y:.1f})",
        )

    def _text(
        self, value: str, x: int, y: int, color: tuple[int, int, int],
        font: pygame.font.Font | None = None,
    ) -> None:
        self.screen.blit((font or self.font).render(value, True, color), (x, y))
