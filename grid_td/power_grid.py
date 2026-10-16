"""Power-grid connectivity and shared efficiency calculation.

This module sits between game state and building entities. `GameState` calls
`PowerGrid.calculate()` after building and on every simulation step. That
method starts from the core, finds adjacent buildings, totals connected supply
and demand, then writes connection flags and efficiency back to every
`Building`. The returned `PowerReport` is read by the status line and tests.

The current algorithm is a four-way breadth-first search (BFS), not the
connection-radius model planned in the design document. Only buildings in
adjacent occupied cells form the network. Efficiency is a shared multiplier
for all connected buildings, with no per-building priority allocation. Any
connectivity-rule change can affect towers, mines, wave difficulty, and
rendered state at the same time.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from grid_td.buildings import Building
from grid_td.map import GridMap
from grid_td.position import Position


@dataclass(frozen=True)
class PowerReport:
    """Read-only summary of one power-grid calculation."""

    connected_count: int  # Number of buildings reachable from the core.
    total_supply: int  # Total supply from connected buildings.
    total_demand: int  # Total demand from connected buildings.
    efficiency: float  # Shared efficiency multiplier from this calculation.


class PowerGrid:
    """Calculate grid connection and work efficiency from building occupancy."""

    MIN_EFFICIENCY = 0.30  # Minimum efficiency with positive but insufficient supply.

    def calculate(self, grid_map: GridMap, buildings: list[Building]) -> PowerReport:
        """Calculate grid state and update every building in place.

        Args:
            grid_map: Map that provides the core root and coordinate rules.
            buildings: All buildings in the current game; list order does not
                affect connectivity.

        Returns:
            A `PowerReport` that counts only buildings connected from the core.

        Side effects:
            Overwrites each building's `connected_to_grid` and `efficiency`.
            Disconnected buildings are explicitly set to 0 efficiency. Callers
            should run this before reading tower or mine behavior.
        """
        # Traverse occupied cells rather than anchors: touching rectangle
        # edges conduct power even when their anchors are several units apart.
        # Count supply/demand once per entity, regardless of footprint area.
        by_position = {
            cell: building
            for building in buildings
            for cell in building.occupied_cells()
        }
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
        """Run four-way BFS through occupied cells starting at the core.

        Empty coordinates stop the current branch. The method does not check
        map bounds because a neighbor is only queued when it exists in
        `by_position`. Shared edges conduct; diagonal-only contact does not.
        Reaching any part of a rectangle also reaches its anchor.
        """
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
        """Calculate the shared whole-grid efficiency from supply and demand.

        No demand counts as full efficiency. Sufficient supply returns 1, zero
        supply returns 0, and all other cases use supply/demand clamped above
        `MIN_EFFICIENCY`.
        """
        if total_demand <= 0:
            return 1.0
        if total_supply >= total_demand:
            return 1.0
        if total_supply <= 0:
            return 0.0
        return max(self.MIN_EFFICIENCY, total_supply / total_demand)

