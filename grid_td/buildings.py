"""Building and tower domain models.

This module defines the core, mines, power sources, power nodes, and three
tower types. These are mutable entities created and driven by the game-state
layer. `GameState` owns lifecycle, build cost, and debt side effects;
`PowerGrid` writes `connected_to_grid` and `efficiency` back to every building;
`TextRenderer` chooses display symbols from concrete building types.

Building objects use dataclasses for runtime state, but the current prototype
does not yet have separate mutable building health: `hp` still returns
`max_hp`. Damage or destruction logic therefore needs a real health source and
clear effects on connectivity and production; changing only the renderer or
power-grid calculation would be incomplete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from grid_td.position import Footprint, LEGACY_TILE_SIZE, Position, WorldPosition


@dataclass
class Building:
    """Base state shared by all buildings.

    `efficiency` is the shared work multiplier from the latest power-grid
    calculation, normally between 0 and 1. It is not building durability.
    Except for `Core`, buildings are normally created by `GameState.build()`
    and updated by `PowerGrid` during waves.
    """

    id: int  # Monotonically assigned by GameState for lookup and identity.
    name: str  # Player-facing display name.
    position: Position  # Top-left anchor in small-cell coordinates.
    cost: int  # One-time gold cost paid when building.
    max_hp: int  # Prototype max health, in integer hit points.
    power_supply: int = 0  # Power supply counted after grid connection.
    power_draw: int = 0  # Power demand counted after grid connection.
    efficiency: float = 0.0  # Work multiplier calculated by PowerGrid.
    connected_to_grid: bool = False  # Whether the core can reach this building.
    needs_repair: bool = False  # Repair marker left by overload-style actions.
    footprint: Footprint = field(init=False)

    # Each concrete type declares its own size. Change that type's FOOTPRINT
    # when introducing different dimensions; placement/power use it directly.
    FOOTPRINT: ClassVar[Footprint] = Footprint(1, 1)

    def __post_init__(self) -> None:
        self.footprint = self.FOOTPRINT

    @property
    def width(self) -> int:
        return self.footprint.width

    @property
    def height(self) -> int:
        return self.footprint.height

    @property
    def center(self) -> WorldPosition:
        """Return the attack/render origin independently of the anchor cell."""
        return self.footprint.center(self.position)

    def occupied_cells(self) -> tuple[Position, ...]:
        """Return every occupied cell, for placement and power traversal."""
        return self.footprint.cells(self.position)

    def occupies(self, position: Position) -> bool:
        """Return whether any part of the building covers the given cell."""
        return self.footprint.contains(self.position, position)

    @property
    def hp(self) -> int:
        """Return current building health.

        The current implementation does not store separate damaged health, so
        this always equals `max_hp`. The property keeps a stable read interface
        for a future damage system.
        """
        return self.max_hp

    @property
    def is_power_source(self) -> bool:
        """Return whether the building provides positive power supply."""
        return self.power_supply > 0

    def can_transmit_power(self) -> bool:
        """Return whether this building can pass grid connectivity onward.

        This method only describes the building's local eligibility. The
        actual connected set is still discovered from the core by
        `PowerGrid._find_connected_positions()`.
        """
        return self.connected_to_grid or self.is_power_source


@dataclass
class Core(Building):
    """Failure target on the map, base power source, and grid root."""

    SYMBOL: ClassVar[str] = "C"  # Map character used by TextRenderer.
    FOOTPRINT: ClassVar[Footprint] = Footprint(1, 1)

    def __init__(self, building_id: int, position: Position) -> None:
        """Create the zero-cost core with fixed health and base power."""
        super().__init__(
            id=building_id,
            name="Core",
            position=position,
            cost=0,
            max_hp=30,
            power_supply=10,
            power_draw=0,
            efficiency=1.0,
            connected_to_grid=True,
        )


@dataclass
class Mine(Building):
    """Economy building restricted to mine sites and settled per wave."""

    SYMBOL: ClassVar[str] = "M"  # Map character used by TextRenderer.
    FOOTPRINT: ClassVar[Footprint] = Footprint(1, 1)
    income: int = 12  # Base settlement income at 100% powered efficiency.

    def __init__(self, building_id: int, position: Position) -> None:
        """Create a mine that only earns income after grid connection."""
        super().__init__(
            id=building_id,
            name="Mine",
            position=position,
            cost=35,
            max_hp=8,
            power_supply=0,
            power_draw=1,
        )
        self.income = 12

    def collect_income(self) -> int:
        """Calculate one income payout from current efficiency, rounded to gold."""
        return round(self.income * self.efficiency)


@dataclass
class PowerPlant(Building):
    """Power source that adds supply after connecting to the core grid."""

    SYMBOL: ClassVar[str] = "P"  # Map character used by TextRenderer.
    FOOTPRINT: ClassVar[Footprint] = Footprint(1, 1)

    def __init__(self, building_id: int, position: Position) -> None:
        """Create a power plant that provides 10 supply when connected."""
        super().__init__(
            id=building_id,
            name="Power Plant",
            position=position,
            cost=50,
            max_hp=10,
            power_supply=10,
            power_draw=0,
        )


@dataclass
class PowerNode(Building):
    """Network relay that transmits power without adding supply."""

    SYMBOL: ClassVar[str] = "N"  # Map character used by TextRenderer.
    FOOTPRINT: ClassVar[Footprint] = Footprint(1, 1)

    def __init__(self, building_id: int, position: Position) -> None:
        """Create a node that extends adjacent-grid connectivity only."""
        super().__init__(
            id=building_id,
            name="Power Node",
            position=position,
            cost=15,
            max_hp=6,
            power_supply=0,
            power_draw=0,
        )


@dataclass
class Tower(Building):
    """Shared attack, cooldown, and overload state for towers.

    A tower can attack only when it is connected to the grid, has positive
    efficiency, and is off cooldown. `GameState._towers_attack()` selects the
    target and applies damage; this class only computes current values and
    maintains timers.
    """

    HIGH_GROUND_BONUS: ClassVar[float] = 1.0

    range: float = 2.0  # World units; measured from the building center.
    damage: float = 1.0  # Base hit damage before efficiency and overload.
    cooldown_seconds: float = 1.0  # Base attack interval at 100% speed.
    cooldown_remaining: float = 0.0  # Logical seconds until the next attack.
    overload_seconds_remaining: float = 0.0  # Logical seconds of overload left.

    @property
    def is_overloaded(self) -> bool:
        """Return whether the tower is currently inside an overload window."""
        return self.overload_seconds_remaining > 0

    def tick_cooldown(self, seconds: float) -> None:
        """Advance attack cooldown and overload timers without going below zero."""
        self.cooldown_remaining = max(0.0, self.cooldown_remaining - seconds)
        self.overload_seconds_remaining = max(0.0, self.overload_seconds_remaining - seconds)

    def can_attack(self) -> bool:
        """Return whether the tower satisfies the basic attack conditions."""
        return self.connected_to_grid and self.efficiency > 0 and self.cooldown_remaining <= 0

    def current_damage(self) -> float:
        """Compute single-hit damage after efficiency and overload modifiers."""
        overload_bonus = 1.75 if self.is_overloaded else 1.0
        return self.damage * self.efficiency * overload_bonus

    def attack_speed_multiplier(self) -> float:
        """Compute attack speed multiplier, capped to avoid zero or huge cooldowns."""
        overload_bonus = 1.5 if self.is_overloaded else 1.0
        return max(0.1, self.efficiency * overload_bonus)

    def reset_cooldown(self) -> None:
        """Set the next attack cooldown after firing."""
        self.cooldown_remaining = self.cooldown_seconds / self.attack_speed_multiplier()

    def overload(self, seconds: float) -> None:
        """Extend the overload window, keeping the longer remaining duration.

        Debt and repair markers are handled by `GameState.overload_tower()`;
        this method only changes the tower-local timer.
        """
        self.overload_seconds_remaining = max(self.overload_seconds_remaining, seconds)


@dataclass
class GunTower(Tower):
    """Low-cost single-target tower with a relatively high fire rate."""

    SYMBOL: ClassVar[str] = "G"  # Map character used by TextRenderer.
    FOOTPRINT: ClassVar[Footprint] = Footprint(1, 1)

    def __init__(self, building_id: int, position: Position, high_ground: bool = False) -> None:
        """Create a fast tower with range 2, or 3 on full high ground."""
        super().__init__(
            id=building_id,
            name="Gun Tower",
            position=position,
            cost=30,
            max_hp=8,
            power_draw=3,
            range=2 + (self.HIGH_GROUND_BONUS if high_ground else 0),
            damage=4.0,
            cooldown_seconds=1.0,
        )


@dataclass
class CannonTower(Tower):
    """High-damage, slower-firing tower.

    The current implementation still treats it as single-target damage; the
    splash damage from the design document is not implemented here yet.
    """

    SYMBOL: ClassVar[str] = "A"  # Map character used by TextRenderer.
    FOOTPRINT: ClassVar[Footprint] = Footprint(1, 1)

    def __init__(self, building_id: int, position: Position, high_ground: bool = False) -> None:
        """Create a slow high-damage tower; currently still single-target."""
        super().__init__(
            id=building_id,
            name="Cannon Tower",
            position=position,
            cost=45,
            max_hp=8,
            power_draw=5,
            range=2 + (self.HIGH_GROUND_BONUS if high_ground else 0),
            damage=8.0,
            cooldown_seconds=2.0,
        )


@dataclass
class SlowTower(Tower):
    """Control tower that deals light damage and applies slow via state logic."""

    SYMBOL: ClassVar[str] = "S"  # Map character used by TextRenderer.
    FOOTPRINT: ClassVar[Footprint] = Footprint(1, 1)

    def __init__(self, building_id: int, position: Position, high_ground: bool = False) -> None:
        """Create a control tower that applies damage plus a fixed 2-second slow."""
        super().__init__(
            id=building_id,
            name="Slow Tower",
            position=position,
            cost=35,
            max_hp=8,
            power_draw=4,
            range=2 + (self.HIGH_GROUND_BONUS if high_ground else 0),
            damage=1.0,
            cooldown_seconds=1.5,
        )


def create_building(kind: str, building_id: int, position: Position, high_ground: bool = False) -> Building:
    """Create a fresh building instance from a stable string kind.

    Args:
        kind: Building key used by `GameState.build()`.
        building_id: Unique entity ID assigned by the caller.
        position: Top-left anchor of the occupied small-cell rectangle.
        high_ground: Whether to apply the high-ground range bonus. Currently
            only affects towers.

    Returns:
        A concrete `Building` subclass instance. No mutable state is shared
        between instances.

    Raises:
        ValueError: `kind` is not one of the supported building keys.

    Note:
        When adding a building type, also update build validation, text-render
        symbols, and relevant tests.
    """
    factories = {
        "mine": Mine,
        "power_plant": PowerPlant,
        "power_node": PowerNode,
        "gun_tower": lambda next_id, pos: GunTower(next_id, pos, high_ground),
        "cannon_tower": lambda next_id, pos: CannonTower(next_id, pos, high_ground),
        "slow_tower": lambda next_id, pos: SlowTower(next_id, pos, high_ground),
    }

    try:
        return factories[kind](building_id, position)
    except KeyError as exc:
        raise ValueError(f"Unknown building kind: {kind}") from exc

