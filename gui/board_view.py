"""Render the spatial snapshot without reading mutable game entities."""

from __future__ import annotations

from pathlib import Path

import pygame

from grid_td.game_state import BuildPreview, BuildingSnapshot, EnemySnapshot, GameSnapshot
from grid_td.position import Position, WorldPosition, world_distance
from gui.styles import (
    ATTACK_RANGE_COLOR,
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
    LIMITED_COLOR,
    MINE_SITE,
    PANEL,
    POWER_RANGE_COLOR,
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
        self.building_sprites = self._load_building_sprites()

    @staticmethod
    def _load_building_sprites() -> dict[str, pygame.Surface]:
        """Cache selected art by snapshot kind; absent assets retain glyph rendering."""
        assets = Path(__file__).resolve().parent / "assets" / "buildings"
        selected = {
            "core": "core-v2.png",
            "mine": "mine-v1.png",
            "gun_tower": "gun-tower-v2.png",
        }
        sprites: dict[str, pygame.Surface] = {}
        for kind, filename in selected.items():
            path = assets / filename
            if path.is_file():
                sprites[kind] = pygame.image.load(str(path)).convert_alpha()
        return sprites

    def position_at(
        self, mouse_pos: tuple[int, int], snapshot: GameSnapshot
    ) -> Position | None:
        """Convert a pixel to a small-cell anchor inside the current map."""
        x = (mouse_pos[0] - BOARD_LEFT) // CELL
        y = (mouse_pos[1] - BOARD_TOP) // CELL
        if 0 <= x < snapshot.width and 0 <= y < snapshot.height:
            return Position(x, y)
        return None

    def _enemy_markers(
        self, snapshot: GameSnapshot
    ) -> list[tuple[EnemySnapshot, tuple[int, int]]]:
        """Share marker positions between drawing and picking continuous enemies."""
        markers = []
        for row in snapshot.board:
            for cell in row:
                for index, enemy in enumerate(cell.enemies):
                    x, y = self._world_point(enemy.world_position, snapshot)
                    if len(cell.enemies) > 1:
                        slot = index % 4
                        x += ((slot % 2) * 2 - 1) * 3
                        y += ((slot // 2) * 2 - 1) * 3
                    markers.append((enemy, (x, y)))
        return markers

    def enemy_at(
        self, mouse_pos: tuple[int, int], snapshot: GameSnapshot
    ) -> EnemySnapshot | None:
        """Pick the nearest drawn marker, with stable IDs breaking exact overlaps."""
        candidates = [
            ((center[0] - mouse_pos[0]) ** 2 + (center[1] - mouse_pos[1]) ** 2, enemy.id, enemy)
            for enemy, center in self._enemy_markers(snapshot)
        ]
        if not candidates:
            return None
        distance, _, enemy = min(candidates, key=lambda item: item[:2])
        return enemy if distance <= 8 ** 2 else None

    def draw(
        self,
        snapshot: GameSnapshot,
        selected_building_id: int | None,
        inspected_position: Position | None,
        hover_position: Position | None,
        preview: BuildPreview | None,
        selected_enemy_id: int | None = None,
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

        # Keep candidate coverage beneath units and the placement outline on top.
        selected = buildings.get(selected_building_id)
        if preview is not None:
            self._draw_build_range(snapshot, preview)
        elif selected is not None and selected.range is not None:
            self._draw_range(snapshot, selected)
        self._draw_buildings(buildings, selected_building_id)
        self._draw_enemies(snapshot, selected_enemy_id, selected.target_enemy_id if selected else None)

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
        self._draw_legend(preview)

    def _draw_legend(self, preview: BuildPreview | None = None) -> None:
        """Explain potential coverage without promising the candidate has power."""
        for x, label, color in (
            (35, "Road", ROUTE),
            (120, "Mine site", MINE_SITE),
            (230, "High ground", HIGH_GROUND),
            (365, "Full output", CHARGED_COLOR),
            (490, "Low output", LIMITED_COLOR),
            (610, "Off grid", UNCHARGED_COLOR),
        ):
            pygame.draw.rect(self.screen, color, pygame.Rect(x, 520, 12, 12))
            text = self.legend_font.render(label, True, TEXT)
            self.screen.blit(text, (x + 17, 518))
        label = "Grid status is shown on buildings; connections can cross empty cells."
        color = TEXT
        if preview is not None:
            power_radius = getattr(preview, "power_radius", None)
            attack_range = getattr(preview, "attack_range", None)
            if power_radius is not None:
                label = f"Power reach: {power_radius:g} world units; requires a grid connection."
                color = POWER_RANGE_COLOR
            elif attack_range is not None:
                label = f"Attack range: {attack_range:g} world units; requires power to attack."
                color = ATTACK_RANGE_COLOR
            if not preview.is_valid:
                color = UNCHARGED_COLOR
        hint = self.legend_font.render(label, True, color)
        self.screen.blit(hint, (35, 540))

    def _draw_range(self, snapshot: GameSnapshot, tower: BuildingSnapshot) -> None:
        """Display the selected tower using the same geometry as hover previews."""
        color = (
            ATTACK_RANGE_COLOR if tower.connected_to_grid and tower.efficiency > 0
            else UNCHARGED_COLOR
        )
        self._draw_range_cells(snapshot, tower.center, tower.range, color)

    def _draw_build_range(self, snapshot: GameSnapshot, preview: BuildPreview) -> None:
        """Read candidate ranges from the public preview, never live entities or constants."""
        # Older core previews can still display their footprint until ranges are exposed.
        center = getattr(preview, "center", None)
        if center is None:
            return
        for radius, color in (
            (getattr(preview, "power_radius", None), POWER_RANGE_COLOR),
            (getattr(preview, "attack_range", None), ATTACK_RANGE_COLOR),
        ):
            if radius is not None:
                self._draw_range_cells(
                    snapshot, center, radius,
                    color if preview.is_valid else UNCHARGED_COLOR,
                )

    @staticmethod
    def _range_cells(
        snapshot: GameSnapshot, center: WorldPosition, radius: float,
    ) -> frozenset[Position]:
        """Test cell centers with the core's shared distance policy and inclusive boundary."""
        return frozenset(
            cell.position for row in snapshot.board for cell in row
            if world_distance(center, cell.position.center) <= radius
        )

    def _draw_range_cells(
        self, snapshot: GameSnapshot, center: WorldPosition, radius: float,
        color: tuple[int, int, int],
    ) -> None:
        """Shade in-bounds cells and outline the coverage without hiding map occupants."""
        cells = self._range_cells(snapshot, center, radius)
        overlay = pygame.Surface((CELL - 2, CELL - 2), pygame.SRCALPHA)
        overlay.fill((*color, 60))
        for position in cells:
            rect = self._cell_rect(position)
            self.screen.blit(overlay, rect.move(1, 1))
            for neighbor, start, end in (
                (Position(position.x - 1, position.y), rect.topleft, (rect.left, rect.bottom - 1)),
                (Position(position.x + 1, position.y), (rect.right - 1, rect.top),
                 (rect.right - 1, rect.bottom - 1)),
                (Position(position.x, position.y - 1), rect.topleft, (rect.right - 1, rect.top)),
                (Position(position.x, position.y + 1), (rect.left, rect.bottom - 1),
                 (rect.right - 1, rect.bottom - 1)),
            ):
                if neighbor not in cells:
                    pygame.draw.line(self.screen, color, start, end)

    def _draw_buildings(
        self, buildings: dict[int, BuildingSnapshot], selected_building_id: int | None
    ) -> None:
        """Draw each footprint once, preserving art paths and overlaying live health."""
        for building in buildings.values():
            rect = self._building_rect(building)
            sprite = self.building_sprites.get(building.kind)
            if sprite is not None:
                # A solid terrain backing keeps map lines out of transparent art.
                backing = MINE_SITE if building.kind == "mine" else GROUND
                pygame.draw.rect(self.screen, backing, rect)
                self.screen.blit(sprite, sprite.get_rect(center=rect.center))
            else:
                color = SYMBOL_COLORS.get(building.symbol, (156, 174, 188))
                pygame.draw.rect(self.screen, color, rect.inflate(-8, -8), border_radius=5)
            # Connectivity and available output are separate snapshot facts.
            if not building.connected_to_grid:
                ring, status = UNCHARGED_COLOR, "OFF"
            elif building.efficiency < 1:
                ring, status = LIMITED_COLOR, "LOW"
            else:
                ring, status = CHARGED_COLOR, ""
            # Show warnings on all art, but keep normal sprites free of green rings.
            if sprite is None or status:
                pygame.draw.rect(
                    self.screen, ring, rect.inflate(-4, -4), 2, border_radius=6
                )
            if building.id == selected_building_id:
                pygame.draw.rect(
                    self.screen, (250, 226, 139), rect.inflate(-1, -1), 2,
                    border_radius=6,
                )
            if sprite is None:
                symbol = self.font.render(building.symbol, True, BACKGROUND)
                self.screen.blit(symbol, symbol.get_rect(center=rect.center))
            if status:
                badge = self.small_font.render(status, True, ring)
                self.screen.blit(badge, badge.get_rect(midbottom=(rect.centerx, rect.bottom - 4)))
            if building.needs_repair:
                warning = self.small_font.render("!", True, UNCHARGED_COLOR)
                self.screen.blit(warning, (rect.right - 13, rect.top + 2))
            if building.hp < building.max_hp:
                bar = pygame.Rect(rect.x + 5, rect.y + 2, rect.width - 10, 3)
                pygame.draw.rect(self.screen, BACKGROUND, bar)
                pygame.draw.rect(
                    self.screen, UNCHARGED_COLOR,
                    (bar.x, bar.y, round(bar.width * building.hp / building.max_hp), bar.height),
                )

    def _draw_enemies(
        self, snapshot: GameSnapshot, selected_enemy_id: int | None,
        manual_target_id: int | None,
    ) -> None:
        """Draw stable-ID enemies with armor, slow, inspection, and manual-target cues."""
        for enemy, center in self._enemy_markers(snapshot):
            color = ENEMY_COLORS.get(enemy.name, ENEMY_COLOR)
            pygame.draw.circle(self.screen, color, center, 5)
            pygame.draw.circle(self.screen, BACKGROUND, center, 5, 1)
            if enemy.is_slowed:
                pygame.draw.circle(self.screen, (111, 214, 228), center, 7, 1)
            if enemy.id == selected_enemy_id:
                pygame.draw.circle(self.screen, (111, 214, 228), center, 10, 2)
            if enemy.id == manual_target_id:
                pygame.draw.circle(self.screen, (250, 226, 139), center, 12, 2)
                label = self.small_font.render(f"TARGET #{enemy.id}", True, (250, 226, 139))
                self.screen.blit(label, (center[0] + 13, center[1] - 7))
            bar = pygame.Rect(center[0] - 5, center[1] - 9, 10, 2)
            pygame.draw.rect(self.screen, BACKGROUND, bar)
            pygame.draw.rect(
                self.screen, CHARGED_COLOR,
                (bar.x, bar.y, round(bar.width * enemy.hp / enemy.max_hp), bar.height),
            )
            if enemy.armor:
                label = self.small_font.render(f"ARM {enemy.armor}", True, TEXT)
                self.screen.blit(label, (center[0] - 14, center[1] + 8))
        for row in snapshot.board:
            for cell in row:
                count = len(cell.enemies)
                if count > 4:
                    label = self.small_font.render(str(count), True, TEXT)
                    self.screen.blit(label, self._cell_rect(cell.position).move(2, 1).topleft)

    def _draw_preview(self, preview: BuildPreview, board_rect: pygame.Rect) -> None:
        """Keep the candidate footprint distinct from its coverage and clip edge placements."""
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
        previous_clip = self.screen.get_clip()
        self.screen.set_clip(board_rect.clip(previous_clip))
        self.screen.blit(overlay, rect.topleft)
        pygame.draw.rect(self.screen, color, rect, 3)
        self.screen.set_clip(previous_clip)

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
