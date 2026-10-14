"""Read-only board drawing and enemy motion between simulation steps."""

from __future__ import annotations

from collections import defaultdict

import pygame

from grid_td.buildings import Building, Tower
from grid_td.enemies import Enemy
from grid_td.game_state import GameState
from grid_td.position import Position
from gui.styles import (
    BACKGROUND,
    BOARD_LEFT,
    BOARD_TOP,
    CELL,
    CHARGED_COLOR,
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
    UNCHARGED_COLOR,
)

ATTACK_EFFECT_SECONDS = 0.1


class BoardView:
    """Draw the map and interpolate enemy positions without changing the game."""

    def __init__(self, game: GameState, screen: pygame.Surface, font: pygame.font.Font) -> None:
        self.game = game
        self.screen = screen
        self.font = font
        # Keep the last visible progress to interpolate between logic steps.
        self.previous_progress: dict[int, float] = {}
        self.animation_elapsed = 1.0
        # Beams store only endpoints and display time; they do not affect combat.
        self.attack_beams: list[tuple[tuple[int, int], tuple[int, int], float]] = []

    def position_at(self, mouse_pos: tuple[int, int]) -> Position | None:
        """Convert window pixels to a board position, or None outside the board."""
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
        """Set the starting positions for surviving enemies' movement animation."""
        self.previous_progress = {
            id(enemy): before.get(id(enemy), 0.0) for enemy in self.game.enemies
        }
        self.animation_elapsed = 0.0 if animate else 1.0

    def capture_combat(self) -> tuple[dict[int, float], list[tuple[Enemy, float, float]]]:
        """Snapshot visible combat state before GameState runs an attack step."""
        cooldowns = {
            building.id: building.cooldown_remaining
            for building in self.game.buildings
            if isinstance(building, Tower)
        }
        enemies = [
            (enemy, enemy.hp, enemy.path_progress)
            for enemy in self.game.enemies
        ]
        return cooldowns, enemies

    def show_combat_results(
        self,
        before: tuple[dict[int, float], list[tuple[Enemy, float, float]]],
        seconds: float,
    ) -> None:
        """Show attacks already resolved by GameState without changing damage."""
        cooldowns, enemies = before
        # The snapshot retains killed enemies after GameState removes them.
        hits: list[list[float]] = []  # Attack-time route progress and unassigned damage.
        known_enemies = {id(enemy) for enemy, _, _ in enemies}
        for enemy, previous_hp, progress in enemies:
            damage = previous_hp - enemy.hp
            if damage > 0:
                hits.append([progress, damage])

        for enemy in self.game.enemies:
            if id(enemy) not in known_enemies and enemy.hp < enemy.max_hp:
                hits.append([0.0, enemy.max_hp - enemy.hp])

        route = self.game.grid_map.route
        for building in self.game.buildings:
            if not isinstance(building, Tower):
                continue
            # A cooldown above its expected decay means the tower fired and reset it.
            expected = max(0.0, cooldowns.get(building.id, 0.0) - seconds)
            if building.cooldown_remaining > expected + 1e-6:
                candidates = [
                    hit for hit in hits
                    if hit[1] > 1e-6
                    and building.position.manhattan_distance(
                        route[min(int(hit[0]), len(route) - 1)]
                    ) <= building.range
                ]
                if candidates:
                    # Prefer the furthest target and subtract damage already assigned.
                    target = max(candidates, key=lambda hit: hit[0])
                    point = self._route_screen_point(target[0])
                    self.attack_beams.append((
                        self._cell_center(building.position),
                        (round(point[0]), round(point[1])),
                        ATTACK_EFFECT_SECONDS,
                    ))
                    target[1] = max(0.0, target[1] - building.current_damage())

    def update(self, seconds: float) -> None:
        """Advance visual effects and remove expired attack beams."""
        self.animation_elapsed = min(1.0, self.animation_elapsed + seconds)
        self.attack_beams = [
            (start, end, remaining - seconds)
            for start, end, remaining in self.attack_beams
            if remaining > seconds
        ]

    def finish_animation(self) -> None:
        self.animation_elapsed = 1.0

    def display_progress(self, enemy: Enemy) -> float:
        """Interpolate an enemy's progress between logic steps."""
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
        """Draw terrain, range, power lines, enemies, buildings, and selection."""
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

        # Highlight route cells within the selected tower's range.
        selected_tower = next(
            (
                building for building in self.game.buildings
                if building.id == selected_tower_id and isinstance(building, Tower)
            ),
            None,
        )
        if selected_tower is not None:
            range_color = (
                (111, 214, 228)
                if selected_tower.connected_to_grid and selected_tower.efficiency > 0
                else UNCHARGED_COLOR
            )
            for position in grid_map.route:
                if selected_tower.position.manhattan_distance(position) <= selected_tower.range:
                    rect = pygame.Rect(
                        BOARD_LEFT + position.x * CELL,
                        BOARD_TOP + position.y * CELL,
                        CELL, CELL,
                    )
                    pygame.draw.rect(
                        self.screen, range_color, rect.inflate(-7, -7), 3,
                        border_radius=4,
                    )

        # Check only right and lower neighbors to draw each power link once.
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

        for start, end, _ in self.attack_beams:
            pygame.draw.line(self.screen, (245, 172, 69), start, end, 6)
            pygame.draw.line(self.screen, (255, 246, 191), start, end, 2)

        for position, building in buildings.items():
            center = self._cell_center(position)
            symbol = getattr(building, "SYMBOL", "?")
            color = SYMBOL_COLORS.get(symbol, (156, 174, 188))
            pygame.draw.circle(self.screen, color, center, 19)
            charged = building.connected_to_grid and building.efficiency > 0
            status_color = CHARGED_COLOR if charged else UNCHARGED_COLOR
            pygame.draw.circle(self.screen, status_color, center, 23, 4)
            if building.id == selected_tower_id:
                pygame.draw.circle(self.screen, (250, 226, 139), center, 29, 2)
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
                self.screen, (111, 214, 228), rect.inflate(-1, -1), 2,
                border_radius=3,
            )

    @staticmethod
    def _cell_center(position: Position) -> tuple[int, int]:
        return (
            BOARD_LEFT + position.x * CELL + CELL // 2,
            BOARD_TOP + position.y * CELL + CELL // 2,
        )

    def _route_screen_point(self, progress: float) -> tuple[float, float]:
        """Map continuous route progress between neighboring cell centers."""
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
        """Group enemies by route cell and spread overlapping markers apart."""
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
                # Offset small groups across the route to avoid overlap.
                offsets = {1: (0,), 2: (-11, 11), 3: (-15, 0, 15)}[count]
                for (enemy, progress), offset in zip(members, offsets):
                    x, y = self._route_screen_point(progress)
                    center = (
                        (round(x + offset), round(y)) if vertical
                        else (round(x), round(y + offset))
                    )
                    self._enemy_marker(enemy, center, 8)
            else:
                # Draw at most nine markers per cell, then show the total count.
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
        bar = pygame.Rect(center[0] - 11, center[1] - radius - 7, 22, 4)
        pygame.draw.rect(self.screen, BACKGROUND, bar)
        fill_width = round(bar.width * max(0.0, enemy.hp / enemy.max_hp))
        if fill_width > 0:
            pygame.draw.rect(self.screen, (113, 218, 142), (bar.x, bar.y, fill_width, bar.height))

    def _center_symbol(
        self, symbol: str, rect: pygame.Rect, color: tuple[int, int, int]
    ) -> None:
        surface = self.font.render(symbol, True, color)
        self.screen.blit(surface, surface.get_rect(center=rect.center))
