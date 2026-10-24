"""Building and tower domain models.

This module defines the core, mines, power sources, power nodes, and three
tower types. These are mutable entities created and driven by the game-state
layer. `GameState` owns lifecycle, build cost, damage, and debt side effects;
`PowerGrid` writes `connected_to_grid` and `efficiency` back to every building;
`TextRenderer` chooses display symbols from concrete building types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import floor
from typing import ClassVar

from grid_td.position import Footprint, LEGACY_TILE_SIZE, Position, WorldPosition


@dataclass
class Building:
    """Base state shared by all buildings.

    `efficiency` is the final work multiplier from the latest power-grid
    calculation after electrical and health-condition factors are combined.
    Except for `Core`, buildings are normally created by `GameState.build()`
    and updated by `PowerGrid` during waves.
    """

    id: int  # Monotonically assigned by GameState for lookup and identity.
    name: str  # Player-facing display name.
    position: Position  # Top-left anchor in small-cell coordinates.
    cost: int  # One-time gold cost paid when building.
    max_hp: int  # Maximum health shared by every building type, including core.
    current_hp: int | None = None  # Mutable health; initialized from max_hp.
    power_supply: int = 0  # Power supply counted after grid connection.
    power_draw: int = 0  # Power demand counted after grid connection.
    efficiency: float = 0.0  # Final work multiplier from power and health.
    connected_to_grid: bool = False  # Whether the core can reach this building.
    needs_repair: bool = False  # Repair marker left by overload-style actions.
    footprint: Footprint = field(init=False)

    # Each concrete type declares its own size. Change that type's FOOTPRINT
    # when introducing different dimensions; placement/power use it directly.
    FOOTPRINT: ClassVar[Footprint] = Footprint(3, 3)
    TRANSMITS_POWER: ClassVar[bool] = False
    REPAIR_GOLD_PER_HP: ClassVar[int] = 1
    # Health is divided into ten-percent bands. A building at 90% health or
    # above keeps full condition efficiency; lower bands reduce it gradually.
    FULL_HEALTH_EFFICIENCY_THRESHOLD: ClassVar[float] = 0.90
    HEALTH_EFFICIENCY_BANDS: ClassVar[int] = 10

    def __post_init__(self) -> None:
        self.footprint = self.FOOTPRINT
        if self.current_hp is None:
            self.current_hp = self.max_hp

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
        """Return the building's current health."""
        assert self.current_hp is not None
        return self.current_hp

    @property
    def is_destroyed(self) -> bool:
        """Return whether the building can no longer operate or relay power."""
        return self.hp <= 0

    def take_damage(self, amount: int) -> None:
        """Apply positive integer damage and clamp health at zero."""
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("Building damage must be a positive integer.")
        self.current_hp = max(0, self.hp - amount)

    @property
    def repair_cost(self) -> int:
        """Quote a full repair at one gold per missing hit point."""
        return max(0, self.max_hp - self.hp) * self.REPAIR_GOLD_PER_HP

    def repair(self) -> int:
        """Restore missing health and return HP restored, including from zero.

        This entity operation does not charge gold or clear overload service
        markers. Player commands must use GameState.repair_building(), which
        validates the game state, charges gold, and refreshes power.
        """
        restored = max(0, self.max_hp - self.hp)
        if restored:
            self.current_hp = self.max_hp
        return restored

    @property
    def health_ratio(self) -> float:
        """Return current health as a clamped ratio in the range 0..1."""
        if self.max_hp <= 0:
            return 0.0
        return min(1.0, max(0.0, self.hp / self.max_hp))

    @property
    def health_efficiency(self) -> float:
        """Return the condition multiplier applied before electrical efficiency.

        The first 10% band (90% to 100% HP) is intentionally lossless. Below
        that threshold each ten-percent band lowers condition efficiency by
        0.1, while zero HP disables the building completely. Integer HP and
        arbitrary max HP values are handled without assuming a fixed health
        scale.
        """
        if self.hp <= 0:
            return 0.0
        if self.health_ratio >= self.FULL_HEALTH_EFFICIENCY_THRESHOLD:
            return 1.0
        # Below the lossless band, the interval [80%, 90%) maps to 0.9,
        # [70%, 80%) maps to 0.8, and so on. The explicit +1 keeps an exact
        # ten-percent boundary in the higher condition band.
        band = floor(self.hp * self.HEALTH_EFFICIENCY_BANDS / self.max_hp) + 1
        return min(1.0, band / self.HEALTH_EFFICIENCY_BANDS)

    def effective_efficiency(self, electrical_efficiency: float) -> float:
        """Combine power availability with condition efficiency."""
        return max(0.0, electrical_efficiency) * self.health_efficiency

    @property
    def effective_power_supply(self) -> int:
        """Return supply after condition effects; ordinary types are unchanged."""
        return self.power_supply

    @property
    def is_power_source(self) -> bool:
        """Return whether the building provides positive power supply."""
        return self.power_supply > 0

    def can_transmit_power(self) -> bool:
        """Return whether this connected building can pass coverage onward."""
        return self.connected_to_grid and self.TRANSMITS_POWER and not self.is_destroyed


@dataclass
class Core(Building):
    """Failure target on the map, base power source, and grid root."""

    SYMBOL: ClassVar[str] = "C"  # Map character used by TextRenderer.
    FOOTPRINT: ClassVar[Footprint] = Footprint(3, 3)
    TRANSMITS_POWER: ClassVar[bool] = True

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
    FOOTPRINT: ClassVar[Footprint] = Footprint(3, 3)
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
        return 0 if self.is_destroyed else round(self.income * self.efficiency)


@dataclass
class PowerPlant(Building):
    """Power source that adds supply after connecting to the core grid."""

    SYMBOL: ClassVar[str] = "P"  # Map character used by TextRenderer.
    FOOTPRINT: ClassVar[Footprint] = Footprint(3, 3)
    TRANSMITS_POWER: ClassVar[bool] = True

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

    @property
    def effective_power_supply(self) -> int:
        """Return health-scaled supply; a destroyed plant provides nothing."""
        if self.is_destroyed:
            return 0
        return round(self.power_supply * self.health_efficiency)


@dataclass
class PowerNode(Building):
    """Network relay that transmits power without adding supply.

    Nodes can be damaged by saboteurs; a destroyed node remains in its cell but
    no longer participates in power propagation.
    """

    SYMBOL: ClassVar[str] = "N"  # Map character used by TextRenderer.
    FOOTPRINT: ClassVar[Footprint] = Footprint(3, 3)
    TRANSMITS_POWER: ClassVar[bool] = True

    def __init__(self, building_id: int, position: Position) -> None:
        """Create a node that extends radius-based power coverage."""
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

    HIGH_GROUND_BONUS: ClassVar[float] = float(LEGACY_TILE_SIZE)

    range: float = 6.0  # World units; measured from the building center.
    damage: float = 1.0  # Base hit damage before efficiency and overload.
    cooldown_seconds: float = 1.0  # Base attack interval at 100% speed.
    cooldown_remaining: float = 0.0  # Logical seconds until the next attack.
    overload_seconds_remaining: float = 0.0  # Logical seconds of overload left.
    target_enemy_id: int | None = None  # Manual target ID; None uses auto selection.

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
        return (
            not self.is_destroyed
            and self.connected_to_grid
            and self.efficiency > 0
            and self.cooldown_remaining <= 0
        )

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
    FOOTPRINT: ClassVar[Footprint] = Footprint(3, 3)

    def __init__(self, building_id: int, position: Position, high_ground: bool = False) -> None:
        """Create a fast tower with range 6, or 9 on full high ground."""
        super().__init__(
            id=building_id,
            name="Gun Tower",
            position=position,
            cost=30,
            max_hp=8,
            power_draw=3,
            range=2 * LEGACY_TILE_SIZE + (self.HIGH_GROUND_BONUS if high_ground else 0),
            damage=4.0,
            cooldown_seconds=1.0,
        )


@dataclass
class CannonTower(Tower):
    """High-damage, slower-firing tower with target-centered splash damage."""

    SYMBOL: ClassVar[str] = "A"  # Map character used by TextRenderer.
    FOOTPRINT: ClassVar[Footprint] = Footprint(3, 3)
    SPLASH_RADIUS: ClassVar[float] = 3.0  # World units around the primary target.
    SPLASH_DAMAGE_RATIO: ClassVar[float] = 0.5  # Secondary damage multiplier.

    def __init__(self, building_id: int, position: Position, high_ground: bool = False) -> None:
        """Create a slow high-damage tower with target-centered splash."""
        super().__init__(
            id=building_id,
            name="Cannon Tower",
            position=position,
            cost=45,
            max_hp=8,
            power_draw=5,
            range=2 * LEGACY_TILE_SIZE + (self.HIGH_GROUND_BONUS if high_ground else 0),
            damage=8.0,
            cooldown_seconds=2.0,
        )


@dataclass
class SlowTower(Tower):
    """Control tower that deals light damage and applies slow via state logic."""

    SYMBOL: ClassVar[str] = "S"  # Map character used by TextRenderer.
    FOOTPRINT: ClassVar[Footprint] = Footprint(3, 3)

    def __init__(self, building_id: int, position: Position, high_ground: bool = False) -> None:
        """Create a control tower that applies damage plus a fixed 2-second slow."""
        super().__init__(
            id=building_id,
            name="Slow Tower",
            position=position,
            cost=35,
            max_hp=8,
            power_draw=4,
            range=2 * LEGACY_TILE_SIZE + (self.HIGH_GROUND_BONUS if high_ground else 0),
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

