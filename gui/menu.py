"""Start and level-selection screens for the playable GUI."""

from __future__ import annotations

import pygame

from gui.styles import BACKGROUND, MUTED, TEXT, WINDOW_SIZE


ACCENT = (94, 216, 172)
GOLD = (225, 185, 105)
CARD = (25, 36, 51)
BORDER = (64, 87, 98)


class MenuView:
    """Draw the pre-game screens and map their buttons to navigation actions."""

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        font_path = next(
            (
                path
                for name in ("microsoftyahei", "simhei", "notosanscjk", "arialunicode")
                if (path := pygame.font.match_font(name)) is not None
            ),
            None,
        )
        self.title_font = pygame.font.Font(font_path, 58)
        self.heading_font = pygame.font.Font(font_path, 34)
        self.body_font = pygame.font.Font(font_path, 22)
        self.small_font = pygame.font.Font(font_path, 17)
        self.button_font = pygame.font.Font(font_path, 23)
        self.buttons = {
            "start": {"enter": pygame.Rect(100, 442, 290, 62)},
            "levels": {
                "play": pygame.Rect(700, 420, 245, 58),
                "back": pygame.Rect(92, 555, 140, 44),
            },
        }

    def action_at(self, view: str, position: tuple[int, int]) -> str | None:
        """Return the action for a clicked menu button, if any."""
        return next(
            (action for action, rect in self.buttons[view].items() if rect.collidepoint(position)),
            None,
        )

    def draw(self, view: str, mouse_pos: tuple[int, int]) -> None:
        """Render a menu screen with the same console palette as the game."""
        self.screen.fill(BACKGROUND)
        self._draw_grid()
        self._text("CRITICAL GRID  /  前线控制台", (94, 53), self.small_font, ACCENT)
        pygame.draw.line(self.screen, BORDER, (92, 91), (988, 91), 1)
        if view == "start":
            self._draw_start(mouse_pos)
        else:
            self._draw_levels(mouse_pos)
        pygame.draw.line(self.screen, BORDER, (92, 620), (988, 620), 1)
        self._text("POWER  •  DEFENSE  •  SURVIVAL", (94, 629), self.small_font, MUTED)

    def _draw_grid(self) -> None:
        """Add a quiet technical grid behind the menu content."""
        for x in range(0, WINDOW_SIZE[0], 54):
            pygame.draw.line(self.screen, (24, 35, 46), (x, 0), (x, WINDOW_SIZE[1]))
        for y in range(0, WINDOW_SIZE[1], 54):
            pygame.draw.line(self.screen, (24, 35, 46), (0, y), (WINDOW_SIZE[0], y))

    def _draw_start(self, mouse_pos: tuple[int, int]) -> None:
        """Show the title, entry action, and a schematic of the defense map."""
        self._text("CRITICAL", (93, 175), self.title_font, TEXT)
        self._text("GRID", (93, 244), self.title_font, ACCENT)
        self._text("建设电网，守住核心。", (100, 348), self.body_font, TEXT)
        self._text("规划资源与防线，抵御一波波进攻。", (100, 386), self.small_font, MUTED)
        self._button(self.buttons["start"]["enter"], "进入   →", mouse_pos)

        # A small map schematic ties the title screen to the grid gameplay.
        panel = pygame.Rect(545, 156, 443, 390)
        pygame.draw.rect(self.screen, CARD, panel, border_radius=12)
        pygame.draw.rect(self.screen, BORDER, panel, width=1, border_radius=12)
        self._text("防线预览  /  GRID STATUS", (571, 180), self.small_font, MUTED)
        cell = 42
        origin = (592, 254)
        for row in range(5):
            for col in range(8):
                rect = pygame.Rect(origin[0] + col * cell, origin[1] + row * cell, 34, 34)
                pygame.draw.rect(self.screen, (43, 61, 70), rect, border_radius=3)
        route = [(0, 3), (1, 3), (2, 3), (3, 3), (4, 3), (5, 3), (5, 2), (5, 1), (6, 1)]
        for col, row in route:
            pygame.draw.rect(
                self.screen,
                (116, 96, 75),
                pygame.Rect(origin[0] + col * cell, origin[1] + row * cell, 34, 34),
                border_radius=3,
            )
        for col, row in ((2, 2), (4, 2), (6, 3)):
            center = (origin[0] + col * cell + 17, origin[1] + row * cell + 17)
            pygame.draw.circle(self.screen, ACCENT, center, 11, width=2)
            pygame.draw.circle(self.screen, ACCENT, center, 3)
        core = (origin[0] + 6 * cell + 17, origin[1] + cell + 17)
        pygame.draw.rect(self.screen, GOLD, pygame.Rect(core[0] - 10, core[1] - 10, 20, 20), width=3)
        self._text("目标：保护核心", (572, 494), self.small_font, GOLD)

    def _draw_levels(self, mouse_pos: tuple[int, int]) -> None:
        """Present the single fixed map currently available in the core."""
        self._text("选择关卡", (92, 125), self.heading_font, TEXT)
        self._text("选择一处前线基地，开始部署。", (94, 175), self.small_font, MUTED)

        card = pygame.Rect(92, 224, 896, 294)
        pygame.draw.rect(self.screen, CARD, card, border_radius=12)
        pygame.draw.rect(self.screen, BORDER, card, width=1, border_radius=12)
        pygame.draw.rect(self.screen, ACCENT, pygame.Rect(92, 224, 5, 294), border_radius=2)
        self._text("01", (123, 255), self.title_font, ACCENT)
        self._text("前线演示", (237, 264), self.heading_font, TEXT)
        self._text("已解锁  /  固定地图", (240, 316), self.small_font, GOLD)
        pygame.draw.line(self.screen, BORDER, (237, 356), (944, 356), 1)
        self._text("36 × 21 小格     单一路线     电网与塔防", (240, 382), self.body_font, MUTED)
        self._button(self.buttons["levels"]["play"], "开始关卡   →", mouse_pos)
        self._button(self.buttons["levels"]["back"], "←  返回", mouse_pos, secondary=True)

    def _button(
        self,
        rect: pygame.Rect,
        label: str,
        mouse_pos: tuple[int, int],
        *,
        secondary: bool = False,
    ) -> None:
        """Draw an accessible text button with a hover state."""
        hovered = rect.collidepoint(mouse_pos)
        if secondary:
            fill = (38, 53, 65) if hovered else CARD
            color = TEXT
        else:
            fill = (125, 231, 188) if hovered else ACCENT
            color = BACKGROUND
        pygame.draw.rect(self.screen, fill, rect, border_radius=6)
        if secondary:
            pygame.draw.rect(self.screen, BORDER, rect, width=1, border_radius=6)
        text = self.button_font.render(label, True, color)
        self.screen.blit(text, text.get_rect(center=rect.center))

    def _text(
        self,
        label: str,
        position: tuple[int, int],
        font: pygame.font.Font,
        color: tuple[int, int, int],
    ) -> None:
        self.screen.blit(font.render(label, True, color), position)
