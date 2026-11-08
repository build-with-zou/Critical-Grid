"""Wave forecasts rendered below the board from immutable snapshots."""

from __future__ import annotations

from html import escape

import pygame
import pygame_gui
from pygame_gui.elements import UIButton, UITextBox

from grid_td.game_state import GameSnapshot
from gui.styles import ATTACK_RANGE_COLOR, PANEL, TEXT


def overview_lines(snapshot: GameSnapshot) -> tuple[str, ...]:
    """Format only the public preview fields and keep the board's entrance order."""
    intel = snapshot.status.free_intel
    if intel is None:
        return ("No incoming wave.",)
    entrances = ", ".join(
        f"E{index}" for index, position in enumerate(snapshot.entrances, 1)
        if position in intel.entrances
    )
    enemies = ", ".join(intel.enemy_names or intel.enemy_kinds)
    traits = ", ".join(tag.replace("_", " ").title() for tag in intel.tags)
    return (
        f"{intel.wave_name}  |  Threat: {intel.threat.title()}",
        f"Entrances: {entrances or 'Unknown'}",
        f"Enemies: {enemies or 'None listed'}",
        f"Traits: {traits or 'None'}",
        intel.briefing,
    )


def detail_lines(snapshot: GameSnapshot, timeline: bool = False) -> tuple[str, ...]:
    """Format the purchased schedule in core order, with time relative to night start."""
    intel = snapshot.status.detailed_intel
    if intel is None or not intel.is_detailed:
        if snapshot.status.free_intel is None:
            return ("No incoming wave.",)
        if snapshot.status.is_finished or snapshot.status.core_hp <= 0:
            return ("Detailed intel is unavailable after the game ends.",)
        return ("Use Wave Intel to unlock counts, groups and spawn times.",)

    def entrance_label(index: int) -> str:
        """Resolve the zero-based schedule index against the map's entrance list."""
        return f"E{index + 1}" if 0 <= index < len(snapshot.entrances) else "Unknown"

    summary = (
        f"{intel.total_enemies} enemies  |  Spawn window {intel.spawn_window_seconds:g}s",
        f"Estimated duration {intel.estimated_duration_seconds:.1f}s",
    )
    if timeline:
        return summary + ("Spawns from night start:",) + tuple(
            f"{spawn.at_seconds:g}s  {spawn.enemy_name}  {entrance_label(spawn.entrance_index)}"
            for spawn in intel.spawn_timeline
        )
    return summary + tuple(
        f"{group.count} × {group.enemy_name}  {entrance_label(group.entrance_index)}\n"
        f"{group.first_spawn_seconds:g}–{group.last_spawn_seconds:g}s"
        f"  |  Interval {group.interval_seconds:g}s"
        for group in intel.groups
    )


class IntelView:
    """Keep public and purchased intel visible in separate scrollable columns."""

    def __init__(
        self, screen: pygame.Surface, manager: pygame_gui.UIManager, font: pygame.font.Font,
    ) -> None:
        """Place the panel and its page controls in the space below the map legend."""
        self.screen = screen
        self.font = font
        manager.get_theme().load_theme({
            "#wave_intel_text": {
                "colours": {"dark_bg": "#101722", "normal_text": "#e8eff4", "normal_border": "#3e4f5c"},
                "misc": {"line_spacing": "1.0", "padding": "6,4"},
            },
        })
        self.overview = UITextBox(
            "", pygame.Rect(38, 599, 312, 132), manager, object_id="#wave_intel_text",
        )
        self.details = UITextBox(
            "", pygame.Rect(360, 599, 320, 132), manager, object_id="#wave_intel_text",
        )
        self.groups_button = UIButton(pygame.Rect(510, 571, 75, 25), "Groups", manager, visible=0)
        self.timeline_button = UIButton(pygame.Rect(589, 571, 91, 25), "Timeline", manager, visible=0)
        self._content = None

    def update(self, snapshot: GameSnapshot) -> None:
        """Refresh on intel changes and reset the detail page when a new wave arrives."""
        status = snapshot.status
        content = (
            status.free_intel, status.detailed_intel, snapshot.entrances,
            status.is_finished or status.core_hp <= 0,
        )
        if content == self._content:
            return
        self._content = content
        self.overview.set_text(self._markup(overview_lines(snapshot)))
        self.show_page(snapshot)

    def show_page(self, snapshot: GameSnapshot, *, timeline: bool = False) -> None:
        """Render either schedule page, with page controls available only after unlock."""
        intel = snapshot.status.detailed_intel
        for button in (self.groups_button, self.timeline_button):
            if intel is not None and intel.is_detailed:
                button.show()
                button.unselect()
            else:
                button.hide()
        if intel is not None and intel.is_detailed:
            (self.timeline_button if timeline else self.groups_button).select()
        self.details.set_text(self._markup(detail_lines(snapshot, timeline)))

    def draw(self) -> None:
        """Draw the panel frame beneath the managed text boxes and buttons."""
        pygame.draw.rect(self.screen, PANEL, pygame.Rect(27, 564, 664, 174), border_radius=7)
        for title, x, color in (
            ("WAVE OVERVIEW", 38, ATTACK_RANGE_COLOR), ("DETAILED INTEL", 360, TEXT),
        ):
            self.screen.blit(self.font.render(title, True, color), (x, 575))

    @staticmethod
    def _markup(lines: tuple[str, ...]) -> str:
        """Treat level-authored text as literal text before adding layout breaks."""
        return "<br>".join(escape(line).replace("\n", "<br>") for line in lines)
