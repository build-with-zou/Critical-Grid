"""Render the spatial snapshot without reading mutable game entities."""

from __future__ import annotations

import pygame

from grid_td.game_state import BuildPreview, BuildingSnapshot, GameSnapshot
from grid_td.position import Position, WorldPosition, world_distance
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


class BoardView:
    """Draw small cells, full building footprints, and continuous enemy positions."""

    def __init__(self, screen: pygame.Surface, font: pygame.font.Font) -> None:
        self.screen = screen
        self.font = font
        self.small_font = pygame.font.SysFont("arial", 12, bold=True)
        self.legend_font = pygame.font.SysFont("arial", 14)

    def position_at(
        self, mouse_pos: tuple[int, int], snapshot: GameSnapshot
    ) -> Position | None:
        """Convert a pixel to a small-cell anchor inside the current map."""
        x = (mouse_pos[0] - BOARD_LEFT) // CELL
        y = (mouse_pos[1] - BOARD_TOP) // CELL
        if 0 <= x < snapshot.width and 0 <= y < snapshot.height:
            return Position(x, y)
        return None

    def draw(
        self,
        snapshot: GameSnapshot,
        selected_tower_id: int | None,
        inspected_position: Position | None,
        hover_position: Position | None,
        preview: BuildPreview | None,
    ) -> None:
        """Draw one coherent frame from a single immutable game snapshot."""
        board_rect = pygame.Rect(
            BOARD_LEFT, BOARD_TOP, snapshot.width * CELL, snapshot.height * CELL
        )
        pygame.draw.rect(
            self.screen, PANEL, board_rect.inflate(16, 16), border_radius=6
        )

        # Each footprint repeats its building in every occupied cell.
        buildings: dict[int, BuildingSnapshot] = {}
        for row in snapshot.board:
            for cell in row:
                rect = self._cell_rect(cell.position)
                color = {
                    "route": ROUTE,
                    "mine_site": MINE_SITE,
                    "high_ground": HIGH_GROUND,
                    "illegal": PANEL,
                }.get(cell.terrain, GROUND)
                pygame.draw.rect(self.screen, color, rect.inflate(-1, -1))
                pygame.draw.rect(self.screen, GRID_LINE, rect, 1)
                if cell.building is not None:
                    buildings[cell.building.id] = cell.building

        # Keep range and power links beneath units; draw interaction outlines last.
        selected = buildings.get(selected_tower_id)
        if selected is not None and selected.range is not None:
            self._draw_range(snapshot, selected)
        self._draw_power_links(snapshot, buildings)
        self._draw_enemies(snapshot)
        self._draw_buildings(buildings, selected_tower_id)

        if inspected_position is not None:
            cell = snapshot.board[inspected_position.y][inspected_position.x]
            rect = (
                self._building_rect(cell.building)
                if cell.building is not None else self._cell_rect(inspected_position)
            )
            pygame.draw.rect(self.screen, (111, 214, 228), rect.inflate(-2, -2), 2)
        if hover_position is not None:
            pygame.draw.rect(
                self.screen, (245, 225, 164),
                self._cell_rect(hover_position).inflate(-2, -2), 2,
            )
        if preview is not None:
            self._draw_preview(preview, board_rect)
        self._draw_legend()

    def _draw_legend(self) -> None:
        """Label terrain and state colors without obscuring the playable map."""
        for x, label, color in (
            (35, "Road", ROUTE),
            (150, "Mine site", MINE_SITE),
            (280, "High ground", HIGH_GROUND),
            (445, "Powered", CHARGED_COLOR),
            (560, "No power", UNCHARGED_COLOR),
        ):
            pygame.draw.rect(self.screen, color, pygame.Rect(x, 520, 12, 12))
            text = self.legend_font.render(label, True, TEXT)
            self.screen.blit(text, (x + 17, 518))
        hint = self.legend_font.render(
            "A colored footprint shows whether the hovered build location is valid.",
            True, TEXT,
        )
        self.screen.blit(hint, (35, 540))

    def _draw_range(self, snapshot: GameSnapshot, tower: BuildingSnapshot) -> None:
        """Shade cells inside the core's current world-distance range policy."""
        overlay = pygame.Surface((CELL - 2, CELL - 2), pygame.SRCALPHA)
        color = (
            (111, 214, 228, 60)
            if tower.connected_to_grid and tower.efficiency > 0
            else (243, 103, 101, 60)
        )
        overlay.fill(color)
        for row in snapshot.board:
            for cell in row:
                if world_distance(tower.center, cell.position.center) <= tower.range:
                    self.screen.blit(overlay, self._cell_rect(cell.position).move(1, 1))

    def _draw_power_links(
        self, snapshot: GameSnapshot, buildings: dict[int, BuildingSnapshot]
    ) -> None:
        """Draw one link for each pair of powered footprints sharing an edge."""
        links: set[tuple[int, int]] = set()
        for row in snapshot.board:
            for cell in row:
                source = cell.building
                if source is None or not source.connected_to_grid:
                    continue
                # Right and down cover every shared edge without scanning it twice.
                for dx, dy in ((1, 0), (0, 1)):
                    x, y = cell.position.x + dx, cell.position.y + dy
                    if x >= snapshot.width or y >= snapshot.height:
                        continue
                    target = snapshot.board[y][x].building
                    if (
                        target is not None and target.id != source.id
                        and target.connected_to_grid
                    ):
                        links.add(tuple(sorted((source.id, target.id))))
        for first, second in links:
            pygame.draw.line(
                self.screen, POWER_LINE,
                self._world_point(buildings[first].center, snapshot),
                self._world_point(buildings[second].center, snapshot), 3,
            )

    def _draw_buildings(
        self, buildings: dict[int, BuildingSnapshot], selected_tower_id: int | None
    ) -> None:
        """Draw each building once despite its presence in several board cells."""
        for building in buildings.values():
            rect = self._building_rect(building)
            color = SYMBOL_COLORS.get(building.symbol, (156, 174, 188))
            pygame.draw.rect(self.screen, color, rect.inflate(-8, -8), border_radius=5)
            charged = building.connected_to_grid and building.efficiency > 0
            ring = CHARGED_COLOR if charged else UNCHARGED_COLOR
            pygame.draw.rect(self.screen, ring, rect.inflate(-4, -4), 2, border_radius=6)
            if building.id == selected_tower_id:
                pygame.draw.rect(
                    self.screen, (250, 226, 139), rect.inflate(-1, -1), 2,
                    border_radius=6,
                )
            symbol = self.font.render(building.symbol, True, BACKGROUND)
            self.screen.blit(symbol, symbol.get_rect(center=rect.center))
            if building.needs_repair:
                warning = self.small_font.render("!", True, UNCHARGED_COLOR)
                self.screen.blit(warning, (rect.right - 13, rect.top + 2))

    def _draw_enemies(self, snapshot: GameSnapshot) -> None:
        """Draw current world positions; snapshots have no stable enemy IDs."""
        for row in snapshot.board:
            for cell in row:
                count = len(cell.enemies)
                # Limit overlapping markers, then show the full count for crowded cells.
                for index, enemy in enumerate(cell.enemies[:4]):
                    x, y = self._world_point(enemy.world_position, snapshot)
                    offset = ((index % 2) * 2 - 1, (index // 2) * 2 - 1)
                    center = (x + offset[0] * 3, y + offset[1] * 3) if count > 1 else (x, y)
                    color = ENEMY_COLORS.get(enemy.name, ENEMY_COLOR)
                    pygame.draw.circle(self.screen, color, center, 5)
                    pygame.draw.circle(self.screen, BACKGROUND, center, 5, 1)
                    bar = pygame.Rect(center[0] - 5, center[1] - 9, 10, 2)
                    pygame.draw.rect(self.screen, BACKGROUND, bar)
                    pygame.draw.rect(
                        self.screen, CHARGED_COLOR,
                        (bar.x, bar.y, round(bar.width * enemy.hp / enemy.max_hp), bar.height),
                    )
                if count > 4:
                    label = self.small_font.render(str(count), True, TEXT)
                    self.screen.blit(label, self._cell_rect(cell.position).move(2, 1).topleft)

    def _draw_preview(self, preview: BuildPreview, board_rect: pygame.Rect) -> None:
        """Mark the entire candidate footprint and its placement validity."""
        rect = pygame.Rect(
            BOARD_LEFT + preview.position.x * CELL,
            BOARD_TOP + preview.position.y * CELL,
            preview.width * CELL,
            preview.height * CELL,
        )
        color = CHARGED_COLOR if preview.is_valid else UNCHARGED_COLOR
        overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
        overlay.fill((*color, 65))
        # An invalid edge placement can extend past the map; confine its preview.
        self.screen.set_clip(board_rect)
        self.screen.blit(overlay, rect.topleft)
        pygame.draw.rect(self.screen, color, rect, 3)
        self.screen.set_clip(None)

    @staticmethod
    def _cell_rect(position: Position) -> pygame.Rect:
        return pygame.Rect(
            BOARD_LEFT + position.x * CELL, BOARD_TOP + position.y * CELL, CELL, CELL
        )

    @staticmethod
    def _building_rect(building: BuildingSnapshot) -> pygame.Rect:
        return pygame.Rect(
            BOARD_LEFT + building.position.x * CELL,
            BOARD_TOP + building.position.y * CELL,
            building.width * CELL, building.height * CELL,
        )

    @staticmethod
    def _world_point(
        position: WorldPosition, snapshot: GameSnapshot
    ) -> tuple[int, int]:
        """Scale continuous world coordinates by the snapshot's cell size."""
        return (
            BOARD_LEFT + round(position.x / snapshot.cell_size * CELL),
            BOARD_TOP + round(position.y / snapshot.cell_size * CELL),
        )
