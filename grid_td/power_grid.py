"""Power-grid connectivity and shared efficiency calculation.

This module sits between game state and building entities. `GameState` calls
`PowerGrid.calculate()` after building and on every simulation step. That
method propagates coverage from the core through power plants and power nodes,
then connects each consumer to its nearest reachable transmitter. The returned
`PowerReport` is read by the status line and tests.

Only the core, power plants, and power nodes are transmitters. A powered mine
or tower cannot relay coverage to another building. Efficiency is still a
shared multiplier for all connected buildings, with no per-building priority
allocation. Any connectivity-rule change can affect towers, mines, wave
difficulty, and rendered state at the same time.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from grid_td.buildings import Building, Core
from grid_td.map import GridMap
from grid_td.position import world_distance


@dataclass(frozen=True)
class PowerReport:
    """Read-only summary of one power-grid calculation."""

    connected_count: int  # Number of buildings reachable from the core.
    total_supply: int  # Total supply from connected buildings.
    total_demand: int  # Total demand from connected buildings.
    efficiency: float  # Shared efficiency multiplier from this calculation.


class PowerGrid:
    """Calculate power connection and work efficiency.

    Power is transmitted by the core, power plants, and power nodes only.
    Other buildings are consumers: being close to a powered mine or tower
    never makes them a relay.  A building is connected when its nearest
    connected transmitter is within ``connection_radius`` world units.
    """

    MIN_EFFICIENCY = 0.30  # Minimum efficiency with positive but insufficient supply.
    DEFAULT_CONNECTION_RADIUS = 6.0

    def __init__(self, connection_radius: float = DEFAULT_CONNECTION_RADIUS) -> None:
        """Create a grid calculator with an inclusive Manhattan radius.

        The default radius is six small-cell world units (two former demo
        tiles).  Keeping it configurable makes custom maps and balance tests
        able to choose a different coverage without changing the game API.
        """
        if isinstance(connection_radius, bool) or not isinstance(connection_radius, (int, float)):
            raise ValueError("Connection radius must be a finite non-negative number.")
        try:
            radius = float(connection_radius)
        except OverflowError:
            raise ValueError("Connection radius must be a finite non-negative number.") from None
        if not isfinite(radius) or radius < 0:
            raise ValueError("Connection radius must be a finite non-negative number.")
        self.connection_radius = radius

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
        # Connectivity is intentionally based on building centers and counts
        # each entity once.  Occupied-cell contact is no longer a requirement:
        # a gap between a node and a tower is valid when it remains within the
        # node's coverage radius.
        connected_indices = self._find_connected_indices(grid_map, buildings)
        connected_buildings = [buildings[index] for index in sorted(connected_indices)]
        total_supply = sum(building.power_supply for building in connected_buildings)
        total_demand = sum(building.power_draw for building in connected_buildings)
        efficiency = self._calculate_efficiency(total_supply, total_demand)

        for index, building in enumerate(buildings):
            building.connected_to_grid = index in connected_indices
            building.efficiency = efficiency if building.connected_to_grid else 0.0

        return PowerReport(
            connected_count=len(connected_buildings),
            total_supply=total_supply,
            total_demand=total_demand,
            efficiency=efficiency,
        )

    def _find_connected_indices(
        self, grid_map: GridMap, buildings: list[Building]
    ) -> set[int]:
        """Return entities reachable through transmitter coverage.

        The propagation pass considers only ``Core``, ``PowerPlant`` and
        ``PowerNode`` as relays.  Consumers are evaluated after all reachable
        relays have been found, so a powered consumer can never extend the
        network to a distant plant or node.
        """
        connected: set[int] = {
            index for index, building in enumerate(buildings)
            if isinstance(building, Core) and building.occupies(grid_map.core_position)
        }
        if not connected:
            return set()

        def is_transmitter(building: Building) -> bool:
            return building.TRANSMITS_POWER

        # Repeatedly add the nearest transmitter that falls inside coverage.
        # ``min`` makes the nearest-source rule explicit and keeps behavior
        # independent of the order in which buildings were constructed.
        changed = True
        while changed:
            changed = False
            transmitters = [
                buildings[index]
                for index in connected
                if is_transmitter(buildings[index])
            ]
            for index, building in enumerate(buildings):
                if index in connected or not is_transmitter(building):
                    continue
                nearest = min(
                    world_distance(building.center, source.center)
                    for source in transmitters
                )
                if nearest <= self.connection_radius:
                    connected.add(index)
                    changed = True

        transmitters = [
            buildings[index]
            for index in connected
            if is_transmitter(buildings[index])
        ]
        for index, building in enumerate(buildings):
            if index in connected or not transmitters:
                continue
            nearest = min(
                world_distance(building.center, source.center)
                for source in transmitters
            )
            if nearest <= self.connection_radius:
                connected.add(index)
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

