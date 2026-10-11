from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from grid_td.buildings import Building
from grid_td.map import GridMap
from grid_td.position import Position


@dataclass(frozen=True)
class PowerReport:
    connected_count: int
    total_supply: int
    total_demand: int
    efficiency: float


class PowerGrid:
    MIN_EFFICIENCY = 0.30

    def calculate(self, grid_map: GridMap, buildings: list[Building]) -> PowerReport:
        by_position = {building.position: building for building in buildings}
        connected_positions = self._find_connected_positions(grid_map, by_position)

        connected_buildings = [
            building for building in buildings if building.position in connected_positions
        ]
        total_supply = sum(building.power_supply for building in connected_buildings)
        total_demand = sum(building.power_draw for building in connected_buildings)
        efficiency = self._calculate_efficiency(total_supply, total_demand)

        for building in buildings:
            building.connected_to_grid = building.position in connected_positions
            building.efficiency = efficiency if building.connected_to_grid else 0.0

        return PowerReport(
            connected_count=len(connected_buildings),
            total_supply=total_supply,
            total_demand=total_demand,
            efficiency=efficiency,
        )

    def _find_connected_positions(
        self,
        grid_map: GridMap,
        by_position: dict[Position, Building],
    ) -> set[Position]:
        connected: set[Position] = set()
        queue: deque[Position] = deque([grid_map.core_position])

        while queue:
            position = queue.popleft()
            if position in connected:
                continue

            building = by_position.get(position)
            if building is None:
                continue

            connected.add(position)

            for neighbor in position.neighbors():
                if neighbor in by_position and neighbor not in connected:
                    queue.append(neighbor)

        return connected

    def _calculate_efficiency(self, total_supply: int, total_demand: int) -> float:
        if total_demand <= 0:
            return 1.0
        if total_supply >= total_demand:
            return 1.0
        if total_supply <= 0:
            return 0.0
        return max(self.MIN_EFFICIENCY, total_supply / total_demand)

