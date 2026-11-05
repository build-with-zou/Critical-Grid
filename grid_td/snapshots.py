"""Read-only presentation contracts for the game state.

The dataclasses in this module are immutable copies of runtime state. They are
the boundary between mutable domain objects in ``grid_td`` and presentation
consumers such as the text renderer and the Pygame GUI. Keeping them in a
separate module prevents the mutable coordinator and its snapshot contract from
growing into one oversized file.

Nothing here imports ``GameState``; the dependency direction is one-way so this
module can be imported by builders, tests, and renderers without cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from grid_td.buildings import (
    Building,
    CannonTower,
    Core,
    GunTower,
    Mine,
    PowerNode,
    PowerPlant,
    PowerPriority,
    SlowTower,
)
from grid_td.intel import WaveIntel
from grid_td.position import Position, WorldPosition


class GamePhase(str, Enum):
    """Lifecycle stages exposed by the core and read-only snapshots.

    Pause is controlled by the caller withholding step() calls; it does not
    replace DAY or NIGHT. String values provide stable frontend labels.
    """

    DAY = "day"
    NIGHT = "night"
    VICTORY = "victory"
    DEFEAT = "defeat"


@dataclass(frozen=True)
class PowerSnapshot:
    """GUI-safe copy of the latest power-grid summary."""

    connected_count: int  # Number of buildings reachable from the core grid.
    total_supply: int  # Connected power supply.
    total_demand: int  # Connected power demand.
    efficiency: float  # Shared electrical multiplier before condition scaling.


@dataclass(frozen=True)
class BuildingSnapshot:
    """Read-only display contract for one building.

    The snapshot intentionally stores primitive values rather than the mutable
    `Building` object, so presentation code cannot accidentally change core
    state while rendering or inspecting a selected cell.
    """

    id: int  # Stable runtime ID used by command APIs such as overload_tower().
    kind: str  # Stable building key for GUI routing and icons.
    name: str  # Player-facing name.
    symbol: str  # Compact text/debug symbol.
    position: Position  # Top-left occupied small cell.
    hp: int  # Current prototype health.
    max_hp: int  # Maximum prototype health.
    cost: int  # Build cost for this building type.
    power_supply: int  # Power provided when connected.
    power_draw: int  # Power consumed when connected.
    connected_to_grid: bool  # Whether the latest power pass reached it.
    power_source_id: int | None  # Direct transmitter supplying this building.
    power_priority: PowerPriority  # Supply allocation tier for consumers.
    power_efficiency: float  # Electrical allocation before condition/transmission.
    efficiency: float  # Final work multiplier after power, health and transmission.
    needs_repair: bool  # Whether wave settlement should charge repair cost.
    width: int
    height: int
    center: WorldPosition
    range: float | None = None  # World-unit tower range; `None` for non-towers.
    damage: float | None = None  # Tower base damage; `None` for non-towers.
    cooldown_remaining: float | None = None  # Tower cooldown; `None` for non-towers.
    is_overloaded: bool = False  # Tower overload flag; always false for non-towers.
    repair_cost: int = 0  # Gold for a full HP repair; excludes overload service fees.
    target_enemy_id: int | None = None  # Manual target enemy ID; None for auto.
    health_efficiency: float = 1.0  # Condition multiplier before power efficiency.
    transmission_efficiency: float = 1.0  # Best node-chain transmission quality.
    effective_power_supply: int = 0  # Health-scaled supply for connected power plants.
    splash_radius: float | None = None  # Cannon splash radius; None for other towers.
    splash_damage_ratio: float | None = None  # Cannon splash multiplier; None otherwise.


@dataclass(frozen=True)
class EnemySnapshot:
    """Read-only display contract for one active enemy."""

    id: int  # Stable runtime ID used by command APIs such as set_tower_target().
    name: str  # Enemy type name.
    position: Position  # Small cell containing the continuous world position.
    hp: float  # Current health.
    max_hp: float  # Maximum health.
    speed: float  # Base world units per second before slow effects.
    damage_to_core: int  # Damage applied if this enemy reaches the core.
    reward: int  # Gold paid when defeated.
    path_progress: float  # World distance traveled along the route.
    is_slowed: bool  # Whether a slow effect is currently active.
    world_position: WorldPosition  # Continuous position in small-cell units.
    armor: int = 0  # Flat damage removed from each positive incoming hit.
    attack_range: float = 0.0  # World-unit range for building attacks.
    attack_damage: int = 0  # Damage per building attack.
    path: tuple[WorldPosition, ...] = ()  # Current route points for preview.
    breach_target_id: int | None = None  # Building this enemy plans to breach.
    target_building_id: int | None = None  # Current active building attack target.
    entrance_index: int = 0  # Spawn point index assigned when the enemy appears.


@dataclass(frozen=True)
class BuildPreview:
    """Read-only placement geometry and potential ranges, without reserving a build.

    Power reach describes a transmitter's potential coverage, not a promise
    that the candidate is connected. Optional defaults preserve callers that
    construct footprint-only previews. build() rechecks before spending.
    """

    kind: str
    position: Position
    width: int
    height: int
    occupied_cells: tuple[Position, ...]
    is_valid: bool
    reason: str
    center: WorldPosition | None = None  # Geometric center of the full candidate footprint.
    attack_range: float | None = None  # Tower range, including any full-high-ground bonus.
    power_radius: float | None = None  # Active grid's radius for transmitter candidates only.


@dataclass(frozen=True)
class CellSnapshot:
    """Read-only display contract for one map cell.

    `terrain` describes the static map layer, while `building` and `enemies`
    describe dynamic occupants. `is_buildable` is a generic placement hint:
    it includes static map rules and occupancy, but building-kind-specific
    rules such as mine-only cells and gold cost still belong to `build()`.
    """

    position: Position
    terrain: str
    is_buildable: bool
    building: BuildingSnapshot | None
    enemies: tuple[EnemySnapshot, ...]

    @property
    def has_enemy(self) -> bool:
        """Return whether at least one active enemy is visible on this cell."""
        return bool(self.enemies)

    @property
    def enemy_count(self) -> int:
        """Return how many active enemies occupy this rendered route cell."""
        return len(self.enemies)

    @property
    def display_symbol(self) -> str:
        """Return the compact text symbol for this cell's visible layer.

        This keeps the draw-priority contract in the snapshot layer, so text
        and GUI renderers can consume the same cell data without duplicating
        the building/enemy/terrain ordering rules.
        """
        if self.building is not None:
            return self.building.symbol
        if self.enemies:
            return "e"
        return {
            "route": "=",
            "core": "C",
            "mine_site": "m",
            "high_ground": "^",
            "illegal": "#",
            "empty": ".",
        }[self.terrain]


@dataclass(frozen=True)
class GameStatus:
    """Read-only status bar contract for GUI and text presentations."""

    gold: int
    debt: int
    core_hp: int
    elapsed_seconds: float
    wave_index: int  # Zero-based index into the configured wave tuple.
    current_wave_name: str
    waiting_for_next_wave: bool
    is_finished: bool
    result_message: str
    power: PowerSnapshot
    phase: GamePhase  # DAY planning, NIGHT combat, or a terminal result.
    free_intel: WaveIntel | None = None  # Coarse current-wave intel, always free.
    detailed_intel: WaveIntel | None = None  # Purchased detailed intel, if unlocked.
    intel_price: int = 8  # Current detailed-intel price for GUI labels.


@dataclass(frozen=True)
class GameSnapshot:
    """Complete read-only presentation snapshot for one render frame."""

    width: int
    height: int
    status: GameStatus
    board: tuple[tuple[CellSnapshot, ...], ...]
    cell_size: float  # One world unit per small cell.
    distance_metric: str
    entrances: tuple[Position, ...] = ()  # Enemy spawn points for this level.


BUILDING_KIND_BY_TYPE: tuple[tuple[type[Building], str], ...] = (
    (Core, "core"),
    (Mine, "mine"),
    (PowerPlant, "power_plant"),
    (PowerNode, "power_node"),
    (GunTower, "gun_tower"),
    (CannonTower, "cannon_tower"),
    (SlowTower, "slow_tower"),
)
