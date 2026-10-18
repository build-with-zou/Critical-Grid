"""Top resource status and bottom event-message rendering."""

from __future__ import annotations

import pygame

from grid_td.game_state import GamePhase, GameSnapshot
from gui.styles import MUTED, PANEL, TEXT


class HUD:
    """Draw game status without handling input or changing simulation state."""

    def __init__(
        self,
        screen: pygame.Surface,
        font: pygame.font.Font,
        small_font: pygame.font.Font,
        title_font: pygame.font.Font,
    ) -> None:
        self.screen = screen
        self.font = font
        self.small_font = small_font
        self.title_font = title_font

    def draw_status(self, snapshot: GameSnapshot, running: bool) -> None:
        """Show phase, wave, resources and power from one immutable snapshot."""
        status = snapshot.status
        report = status.power
        activity = (
            "PLANNING" if status.phase == GamePhase.DAY
            else "RUNNING" if running and status.phase == GamePhase.NIGHT
            else "PAUSED" if status.phase == GamePhase.NIGHT
            else "FINISHED"
        )
        pygame.draw.rect(
            self.screen, PANEL, pygame.Rect(18, 16, 1044, 96), border_radius=8
        )
        self._text("CRITICAL GRID", 34, 25, font=self.title_font)
        self._text(
            f"{status.current_wave_name}"
            f"   {status.phase.value.upper()}   {activity}"
            f"   Time {status.elapsed_seconds:.1f}s",
            339, 32, color=MUTED,
        )
        self._text(
            f"Gold {status.gold}    Debt {status.debt}    Core HP {status.core_hp}"
            f"    Power {report.total_supply}/{report.total_demand}"
            f"    Efficiency {report.efficiency:.0%}",
            34, 76, font=self.small_font,
        )

    def draw_message(self, message: str) -> None:
        """Wrap the event message by rendered width and show at most two lines."""
        pygame.draw.rect(
            self.screen, PANEL, pygame.Rect(18, 568, 1044, 76), border_radius=8
        )
        self._text("EVENT", 34, 579, color=MUTED, font=self.small_font)
        words = message.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            # Measure rendered width so variable-width text stays inside the panel.
            if current and self.small_font.size(candidate)[0] > 1000:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        for index, line in enumerate(lines[:2]):
            self._text(line, 34, 602 + index * 22, font=self.small_font)

    def _text(
        self,
        value: str,
        x: int,
        y: int,
        *,
        color: tuple[int, int, int] = TEXT,
        font: pygame.font.Font | None = None,
    ) -> None:
        surface = (font or self.font).render(value, True, color)
        self.screen.blit(surface, (x, y))
