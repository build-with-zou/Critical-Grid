"""Construction of immutable presentation snapshots.

`SnapshotBuilder` turns mutable map, building, and enemy state into the
dataclasses in ``grid_td.snapshots``. Static terrain labels and buildable flags
are computed once per map object, so repeated frames reuse them instead of
re-querying every cell. Dynamic occupancy is rebuilt each call because it
changes when buildings are placed, sold, or destroyed.

The builder never mutates domain state. It is created by ``GameState`` and
recreated when the map object changes, which keeps cached static data correct
for tests that replace ``game.grid_map``.
"""

from __future__ import annotations

from grid_td.buildings import Building, CannonTower, Tower
from grid_td.enemies import Enemy
from grid_td.map import GridMap
from grid_td.position import Position
from grid_td.snapshots import (
    BUILDING_KIND_BY_TYPE,
    BuildingSnapshot,
    CellSnapshot,
    EnemySnapshot,
)


class SnapshotBuilder:
    """Build read-only snapshots for one immutable map."""

    def __init__(self, grid_map: GridMap) -> None:
        """Precompute static map layers that only change when the map changes."""
        self.grid_map = grid_map
        self._positions: tuple[tuple[Position, ...], ...] = tuple(
            tuple(Position(x, y) for x in range(grid_map.width))
            for y in range(grid_map.height)
        )
        self._terrain: tuple[tuple[str, ...], ...] = tuple(
            tuple(self._terrain_at(position) for position in row)
            for row in self._positions
        )
        self._buildable: tuple[tuple[bool, ...], ...] = tuple(
            tuple(grid_map.is_buildable(position) for position in row)
            for row in self._positions
        )

    def _terrain_at(self, position: Position) -> str:
        """Return the static terrain label using the draw-priority order."""
        if self.grid_map.is_core(position):
            return "core"
        if self.grid_map.is_route(position):
            return "route"
        if self.grid_map.is_mine_site(position):
            return "mine_site"
        if self.grid_map.is_high_ground(position):
            return "high_ground"
        if self.grid_map.is_illegal(position):
            return "illegal"
        return "empty"

    def building_kind(self, building: Building) -> str:
        """Return the stable command/API key for a building instance."""
        for building_type, kind in BUILDING_KIND_BY_TYPE:
            if isinstance(building, building_type):
                return kind
        return type(building).__name__

    def building_snapshot(self, building: Building) -> BuildingSnapshot:
        """Copy mutable building state into a presentation-safe value object."""
        tower = building if isinstance(building, Tower) else None
        return BuildingSnapshot(
            id=building.id,
            kind=self.building_kind(building),
            name=building.name,
            symbol=getattr(type(building), "SYMBOL", "?"),
            position=building.position,
            hp=building.hp,
            max_hp=building.max_hp,
            cost=building.cost,
            power_supply=building.power_supply,
            power_draw=building.power_draw,
            connected_to_grid=building.connected_to_grid,
            power_source_id=building.power_source_id,
            power_priority=building.power_priority,
            power_efficiency=building.power_efficiency,
            efficiency=building.efficiency,
            needs_repair=building.needs_repair,
            width=building.width,
            height=building.height,
            center=building.center,
            range=tower.range if tower is not None else None,
            damage=tower.damage if tower is not None else None,
            cooldown_remaining=tower.cooldown_remaining if tower is not None else None,
            is_overloaded=tower.is_overloaded if tower is not None else False,
            repair_cost=building.repair_cost,
            target_enemy_id=tower.target_enemy_id if tower is not None else None,
            health_efficiency=building.health_efficiency,
            transmission_efficiency=building.transmission_efficiency,
            effective_power_supply=building.effective_power_supply,
            splash_radius=(
                building.SPLASH_RADIUS if isinstance(building, CannonTower) else None
            ),
            splash_damage_ratio=(
                building.SPLASH_DAMAGE_RATIO
                if isinstance(building, CannonTower) else None
            ),
        )

    def enemy_snapshots_by_position(
        self, enemies: list[Enemy]
    ) -> dict[Position, tuple[EnemySnapshot, ...]]:
        """Group active enemies by their rendered route cell."""
        grouped: dict[Position, list[EnemySnapshot]] = {}
        for enemy in enemies:
            if not enemy.is_alive:
                continue

            active_path = enemy.active_path(self.grid_map.path)
            world_position = enemy.world_position_on_route(active_path)
            position = world_position.cell
            grouped.setdefault(position, []).append(
                EnemySnapshot(
                    id=enemy.id,
                    name=enemy.name,
                    position=position,
                    hp=enemy.hp,
                    max_hp=enemy.max_hp,
                    speed=enemy.speed,
                    damage_to_core=enemy.damage_to_core,
                    reward=enemy.reward,
                    path_progress=enemy.path_progress,
                    is_slowed=enemy.is_slowed,
                    world_position=world_position,
                    armor=enemy.armor,
                    attack_range=enemy.attack_range,
                    attack_damage=enemy.attack_damage,
                    path=active_path.points,
                    breach_target_id=enemy.breach_target_id,
                    target_building_id=enemy.target_building_id,
                    entrance_index=enemy.entrance_index,
                )
            )

        return {
            position: tuple(enemies)
            for position, enemies in grouped.items()
        }

    def _occupancy(
        self, buildings: list[Building]
    ) -> dict[Position, BuildingSnapshot]:
        """Copy each building once and index it by every covered cell."""
        occupancy: dict[Position, BuildingSnapshot] = {}
        for building in buildings:
            snapshot = self.building_snapshot(building)
            for cell in building.occupied_cells():
                occupancy[cell] = snapshot
        return occupancy

    def board(
        self, buildings: list[Building], enemies: list[Enemy]
    ) -> tuple[tuple[CellSnapshot, ...], ...]:
        """Return a row-major immutable snapshot of the whole board."""
        occupancy = self._occupancy(buildings)
        enemies_by_position = self.enemy_snapshots_by_position(enemies)
        return tuple(
            tuple(
                CellSnapshot(
                    position=position,
                    terrain=self._terrain[y][x],
                    is_buildable=self._buildable[y][x] and position not in occupancy,
                    building=occupancy.get(position),
                    enemies=enemies_by_position.get(position, ()),
                )
                for x, position in enumerate(row)
            )
            for y, row in enumerate(self._positions)
        )

    def cell(
        self, position: Position, buildings: list[Building], enemies: list[Enemy]
    ) -> CellSnapshot:
        """Return one cell snapshot; the caller must pass an in-bounds cell."""
        building = next(
            (candidate for candidate in buildings if candidate.occupies(position)),
            None,
        )
        return CellSnapshot(
            position=position,
            terrain=self._terrain[position.y][position.x],
            is_buildable=(
                self._buildable[position.y][position.x] and building is None
            ),
            building=(
                self.building_snapshot(building) if building is not None else None
            ),
            enemies=self.enemy_snapshots_by_position(enemies).get(position, ()),
        )
