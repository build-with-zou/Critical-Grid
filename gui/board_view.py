"""Read-only board drawing and enemy motion between simulation steps."""

from __future__ import annotations

from collections import defaultdict

import pygame

from grid_td.buildings import Building
from grid_td.enemies import Enemy
from grid_td.game_state import GameState
from grid_td.position import Position
from gui.styles import (
    BACKGROUND,
    BOARD_LEFT,
    BOARD_TOP,
    CELL,
    ENEMY_COLOR,
    ENEMY_COLORS,
    GRID_LINE,
    GROUND,
    HIGH_GROUND,
    MINE_SITE,
    PANEL,
    POWER_LINE,
    ROUTE,
    SYMBOL_COLORS,
    TEXT,
)


class BoardView:
    """Draw the map and interpolate enemy positions without changing the game."""

    def __init__(self, game: GameState, screen: pygame.Surface, font: pygame.font.Font) -> None:
        self.game = game
        self.screen = screen
        self.font = font
        self.previous_progress: dict[int, float] = {}
        self.animation_elapsed = 1.0

    def position_at(self, mouse_pos: tuple[int, int]) -> Position | None:
        x = (mouse_pos[0] - BOARD_LEFT) // CELL
        y = (mouse_pos[1] - BOARD_TOP) // CELL
        position = Position(x, y)
        if mouse_pos[0] < BOARD_LEFT or mouse_pos[1] < BOARD_TOP:
            return None
        return position if self.game.grid_map.in_bounds(position) else None

    def capture_progress(self) -> dict[int, float]:
        """Remember what the player currently sees before a logic step."""
        return {id(enemy): self.display_progress(enemy) for enemy in self.game.enemies}

    def complete_step(self, before: dict[int, float], *, animate: bool) -> None:
        self.previous_progress = {
            id(enemy): before.get(id(enemy), 0.0) for enemy in self.game.enemies
        }
        self.animation_elapsed = 0.0 if animate else 1.0

    def update(self, seconds: float) -> None:
        self.animation_elapsed = min(1.0, self.animation_elapsed + seconds)

    def finish_animation(self) -> None:
        self.animation_elapsed = 1.0

    def display_progress(self, enemy: Enemy) -> float:
        current = enemy.path_progress
        start = self.previous_progress.get(id(enemy), current)
        fraction = min(self.animation_elapsed, 1.0)
        return start + (current - start) * fraction

    def draw(
        self,
        selected_tower_id: int | None,
        inspected_position: Position | None,
        *,
        show_hover: bool,
    ) -> None:
        grid_map = self.game.grid_map
        board_width = grid_map.width * CELL
        board_height = grid_map.height * CELL
        pygame.draw.rect(
            self.screen,
            PANEL,
            pygame.Rect(
                BOARD_LEFT - 8, BOARD_TOP - 8,
                board_width + 16, board_height + 16,
            ),
            border_radius=6,
        )

        buildings = {building.position: building for building in self.game.buildings}
        for y in range(grid_map.height):
            for x in range(grid_map.width):
                position = Position(x, y)
                rect = pygame.Rect(BOARD_LEFT + x * CELL, BOARD_TOP + y * CELL, CELL, CELL)
                if grid_map.is_route(position):
                    color = ROUTE
                elif grid_map.is_mine_site(position):
                    color = MINE_SITE
                elif grid_map.is_high_ground(position):
                    color = HIGH_GROUND
                else:
                    color = GROUND
                pygame.draw.rect(self.screen, color, rect.inflate(-2, -2), border_radius=3)
                pygame.draw.rect(self.screen, GRID_LINE, rect, 1)
                if position not in buildings and grid_map.is_mine_site(position):
                    self._center_symbol("$", rect, (235, 204, 116))
                elif position not in buildings and grid_map.is_high_ground(position):
                    self._center_symbol("^", rect, (160, 198, 226))

        for position, building in buildings.items():
            if not building.connected_to_grid:
                continue
            for neighbor in (
                Position(position.x + 1, position.y),
                Position(position.x, position.y + 1),
            ):
                adjacent = buildings.get(neighbor)
                if adjacent is not None and adjacent.connected_to_grid:
                    pygame.draw.line(
                        self.screen, POWER_LINE,
                        self._cell_center(position), self._cell_center(neighbor), 4,
                    )

        self._draw_enemies(buildings)

        for position, building in buildings.items():
            center = self._cell_center(position)
            symbol = getattr(building, "SYMBOL", "?")
            color = SYMBOL_COLORS.get(symbol, (156, 174, 188))
            pygame.draw.circle(self.screen, color, center, 19)
            if building.id == selected_tower_id:
                pygame.draw.circle(self.screen, (250, 226, 139), center, 24, 3)
            if not building.connected_to_grid:
                pygame.draw.circle(self.screen, ENEMY_COLOR, center, 22, 3)
            self._center_symbol(
                symbol,
                pygame.Rect(center[0] - 22, center[1] - 22, 44, 44),
                BACKGROUND,
            )

        hover = self.position_at(pygame.mouse.get_pos()) if show_hover else None
        if hover is not None:
            rect = pygame.Rect(
                BOARD_LEFT + hover.x * CELL, BOARD_TOP + hover.y * CELL, CELL, CELL
            )
            pygame.draw.rect(
                self.screen, (245, 225, 164), rect.inflate(-2, -2), 2,
                border_radius=3,
            )
        if inspected_position is not None:
            rect = pygame.Rect(
                BOARD_LEFT + inspected_position.x * CELL,
                BOARD_TOP + inspected_position.y * CELL,
                CELL, CELL,
            )
            pygame.draw.rect(
                self.screen, (111, 214, 228), rect.inflate(-5, -5), 2,
                border_radius=3,
            )

    @staticmethod
    def _cell_center(position: Position) -> tuple[int, int]:
        return (
            BOARD_LEFT + position.x * CELL + CELL // 2,
            BOARD_TOP + position.y * CELL + CELL // 2,
        )

    def _route_screen_point(self, progress: float) -> tuple[float, float]:
        route = self.game.grid_map.route
        progress = max(0.0, min(progress, float(len(route) - 1)))
        index = int(progress)
        start = self._cell_center(route[index])
        if index == len(route) - 1:
            return float(start[0]), float(start[1])
        end = self._cell_center(route[index + 1])
        fraction = progress - index
        return (
            start[0] + (end[0] - start[0]) * fraction,
            start[1] + (end[1] - start[1]) * fraction,
        )

    def _draw_enemies(self, buildings: dict[Position, Building]) -> None:
        route = self.game.grid_map.route
        groups: dict[int, list[tuple[Enemy, float]]] = defaultdict(list)
        for enemy in self.game.enemies:
            if not enemy.is_alive:
                continue
            progress = self.display_progress(enemy)
            tile_index = min(int(progress), len(route) - 1)
            if route[tile_index] not in buildings:
                groups[tile_index].append((enemy, progress))

        for tile_index, members in groups.items():
            tile = route[tile_index]
            count = len(members)
            next_tile = route[min(tile_index + 1, len(route) - 1)]
            vertical = next_tile.x == tile.x and next_tile.y != tile.y
            if count <= 3:
                offsets = {1: (0,), 2: (-11, 11), 3: (-15, 0, 15)}[count]
                for (enemy, progress), offset in zip(members, offsets):
                    x, y = self._route_screen_point(progress)
                    center = (
                        (round(x + offset), round(y)) if vertical
                        else (round(x), round(y + offset))
                    )
                    self._enemy_marker(enemy, center, 8)
            else:
                visible = members[:9]
                rows = (len(visible) + 2) // 3
                for index, (enemy, progress) in enumerate(visible):
                    col, row = index % 3, index // 3
                    x, y = self._route_screen_point(progress)
                    lane = (col - 1) * 16
                    stagger = round((row - (rows - 1) / 2) * 16)
                    point = (
                        (round(x + lane), round(y + stagger)) if vertical
                        else (round(x + stagger), round(y + lane))
                    )
                    self._enemy_marker(enemy, point, 7)
                if count > 9:
                    center = self._cell_center(tile)
                    number = self.font.render(str(count), True, TEXT)
                    self.screen.blit(number, (center[0] + 12, center[1] - 26))

    def _enemy_marker(self, enemy: Enemy, center: tuple[int, int], radius: int) -> None:
        color = ENEMY_COLORS.get(enemy.name, ENEMY_COLOR)
        pygame.draw.circle(self.screen, color, center, radius)
        pygame.draw.circle(self.screen, BACKGROUND, center, radius, 1)

    def _center_symbol(
        self, symbol: str, rect: pygame.Rect, color: tuple[int, int, int]
    ) -> None:
        surface = self.font.render(symbol, True, color)
        self.screen.blit(surface, surface.get_rect(center=rect.center))
