"""Game-state aggregate and core simulation loop.

`GameState` is the single runtime coordinator. It owns the map, gold/debt,
buildings, enemies, core health, wave progress, and result state. It exposes
operations for building, selling, repair, targeting, intel, overdraft,
overload, wave settlement, and each time step; `PowerGrid`, `WaveRunner`,
`Building`, and `Enemy` provide the local rules it calls. Read-only presentation code should use `snapshot()`
instead of reading mutable attributes directly.

Key state-flow boundaries:

* `build()` changes the building list and gold, then recalculates power.
* New games start in DAY with no active wave runner.
* `start_next_wave()` ends planning and creates a fresh NIGHT runner.
* During NIGHT, `step()` spawns enemies, recalculates power, runs tower
  attacks, moves enemies, then lets saboteurs attack power buildings. During DAY
  it leaves simulation time frozen.
* `end_wave()` settles income, interest, and repairs, then enters the next
  DAY or records VICTORY. Core destruction records DEFEAT immediately.

This module does not handle input devices or UI rendering. `TextRenderer`
should only read state from here. Add new gameplay operations as explicit
methods on this class before allowing presentation code to mutate lists or
resources directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import ClassVar

from grid_td.buildings import (
    Building,
    CannonTower,
    Core,
    GunTower,
    Mine,
    PowerNode,
    PowerPlant,
    SlowTower,
    Tower,
    create_building,
)
from grid_td.enemies import Enemy
from grid_td.map import GridMap
from grid_td.position import DISTANCE_METRIC, Position, WorldPosition, world_distance
from grid_td.power_grid import PowerGrid, PowerReport
from grid_td.waves import WaveRunner, create_demo_waves


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
    efficiency: float  # Final work multiplier after power and condition scaling.
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


@dataclass(frozen=True)
class BuildPreview:
    """Read-only placement result; build() always rechecks before spending."""

    kind: str
    position: Position
    width: int
    height: int
    occupied_cells: tuple[Position, ...]
    is_valid: bool
    reason: str


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


@dataclass(frozen=True)
class GameSnapshot:
    """Complete read-only presentation snapshot for one render frame."""

    width: int
    height: int
    status: GameStatus
    board: tuple[tuple[CellSnapshot, ...], ...]
    cell_size: float  # One world unit per small cell.
    distance_metric: str


BUILDING_KIND_BY_TYPE: tuple[tuple[type[Building], str], ...] = (
    (Core, "core"),
    (Mine, "mine"),
    (PowerPlant, "power_plant"),
    (PowerNode, "power_node"),
    (GunTower, "gun_tower"),
    (CannonTower, "cannon_tower"),
    (SlowTower, "slow_tower"),
)


@dataclass(init=False)
class GameState:
    """Mutable state and public operation entry point for one game run."""

    # Fraction of build cost refunded by sell_building(); the core is never sold.
    SELL_REFUND_RATIO: ClassVar[float] = 0.7

    grid_map: GridMap
    gold: int = 180  # Current spendable gold; build, intel, and settlement change it.
    debt: int = 0  # Debt from overdraft/overload; interest is charged at wave end.
    elapsed_seconds: float = 0.0  # Authoritative logical clock, measured in seconds.
    buildings: list[Building] = field(default_factory=list)  # Current building entities.
    enemies: list[Enemy] = field(default_factory=list)  # Living enemies on the board.
    phase: GamePhase = field(default=GamePhase.DAY, init=False)
    _core: Core = field(init=False, repr=False)

    def __init__(
        self,
        grid_map: GridMap,
        gold: int = 180,
        debt: int = 0,
        core_hp: int = 30,
        elapsed_seconds: float = 0.0,
        buildings: list[Building] | None = None,
        enemies: list[Enemy] | None = None,
    ) -> None:
        """Keep the existing constructor while storing core HP on the core.

        A custom initializer lets core_hp remain a compatibility property
        rather than a second mutable health counter.
        """
        self.grid_map = grid_map
        self.gold = gold
        self.debt = debt
        self.elapsed_seconds = elapsed_seconds
        self.buildings = buildings if buildings is not None else []
        self.enemies = enemies if enemies is not None else []
        self.phase = GamePhase.DAY
        self.__post_init__(core_hp)

    def __post_init__(self, core_hp: int = 30) -> None:
        """Initialize runtime collaborators, wave state, the core, and power.

        Attributes such as `power_grid`, `waves`, and `wave_index` are derived
        runtime state and are not exposed as dataclass constructor parameters,
        which avoids inconsistent schedulers being injected by callers. The
        core is added to the building list here, so a passed-in `buildings`
        list is extended in place.
        """
        self.power_grid = PowerGrid()
        self.waves = create_demo_waves()
        self.wave_index = 0
        # The upcoming wave index exists during planning, but its clock must
        # not start until the player explicitly ends the day.
        self.wave_runner: WaveRunner | None = None
        self.next_building_id = 1
        self.next_enemy_id = 1
        self.result_message = ""
        self.latest_power_report = PowerReport(0, 0, 0, 1.0)
        core = Core(self._next_id(), self.grid_map.core_position)
        self._core = core
        # Custom starting health may exceed the default in scenarios/tests.
        core.max_hp = max(core.max_hp, core_hp)
        self.core_hp = core_hp
        # Match the map's reservation, including custom core dimensions.
        core.footprint = self.grid_map.core_footprint
        self._add_building(core)
        self.recalculate_power()

    @property
    def core_hp(self) -> int:
        """Expose core health without duplicating the core entity's state."""
        return self._core.hp

    @core_hp.setter
    def core_hp(self, value: int) -> None:
        """Preserve existing core_hp assignments used by scenarios and tests."""
        self._core.current_hp = value

    @property
    def is_finished(self) -> bool:
        """Return whether a terminal phase or existing result ends the run."""
        return (
            self.phase in (GamePhase.VICTORY, GamePhase.DEFEAT)
            or bool(self.result_message)
        )

    @property
    def waiting_for_next_wave(self) -> bool:
        """Return whether an unfinished game has a wave ready to settle.

        Spawning must be complete and no enemies may remain before
        `end_wave()` is allowed. A finished game or destroyed core is never
        ready for settlement.
        """
        if (
            self.is_finished
            or self.core_hp <= 0
            or self.phase != GamePhase.NIGHT
            or self.wave_runner is None
        ):
            return False
        return self.wave_runner.is_complete and not self.enemies

    @property
    def current_wave_name(self) -> str:
        """Return the current wave name, or fixed text after all waves finish."""
        if self.wave_index >= len(self.waves):
            return "No more waves"
        return self.waves[self.wave_index].name

    def snapshot(self) -> GameSnapshot:
        """Return the single read-only data source for presentation layers.

        GUI and text code should call this method when they need to inspect
        state. Command methods such as `build()`, `step()`, and `end_wave()`
        remain the only supported way for external code to change gameplay.
        """
        return GameSnapshot(
            width=self.grid_map.width,
            height=self.grid_map.height,
            status=self.status_snapshot(),
            board=self.board_snapshot(),
            cell_size=1.0,
            distance_metric=DISTANCE_METRIC,
        )

    def status_snapshot(self) -> GameStatus:
        """Return the current top-level game status without mutable entities."""
        report = self.latest_power_report
        return GameStatus(
            gold=self.gold,
            debt=self.debt,
            core_hp=self.core_hp,
            elapsed_seconds=self.elapsed_seconds,
            wave_index=self.wave_index,
            current_wave_name=self.current_wave_name,
            waiting_for_next_wave=self.waiting_for_next_wave,
            is_finished=self.is_finished,
            result_message=self.result_message,
            phase=self.phase,
            power=PowerSnapshot(
                connected_count=report.connected_count,
                total_supply=report.total_supply,
                total_demand=report.total_demand,
                efficiency=report.efficiency,
            ),
        )

    def board_snapshot(self) -> tuple[tuple[CellSnapshot, ...], ...]:
        """Return a row-major immutable snapshot of the whole board."""
        enemies_by_position = self._enemy_snapshots_by_position()
        return tuple(
            tuple(
                self._cell_snapshot(Position(x, y), enemies_by_position)
                for x in range(self.grid_map.width)
            )
            for y in range(self.grid_map.height)
        )

    def cell_snapshot(self, position: Position) -> CellSnapshot:
        """Return a read-only snapshot for one in-bounds map cell.

        Raises:
            ValueError: The requested position is outside the map.
        """
        if not self.grid_map.in_bounds(position):
            raise ValueError(f"Position is out of bounds: {position}")
        return self._cell_snapshot(position, self._enemy_snapshots_by_position())

    def _cell_snapshot(
        self,
        position: Position,
        enemies_by_position: dict[Position, tuple[EnemySnapshot, ...]],
    ) -> CellSnapshot:
        """Build one cell snapshot from precomputed occupant lookups."""
        building = self.building_at(position)
        return CellSnapshot(
            position=position,
            terrain=self._terrain_at(position),
            is_buildable=self.grid_map.is_buildable(position) and building is None,
            building=self._building_snapshot(building) if building is not None else None,
            enemies=enemies_by_position.get(position, ()),
        )

    def _terrain_at(self, position: Position) -> str:
        """Return the static terrain label for a map position.

        The order mirrors the existing render priority for static layers.
        Dynamic occupants are intentionally excluded and appear separately in
        `CellSnapshot.building` and `CellSnapshot.enemies`.
        """
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

    def _building_snapshot(self, building: Building) -> BuildingSnapshot:
        """Copy mutable building state into a presentation-safe value object."""
        tower = building if isinstance(building, Tower) else None
        return BuildingSnapshot(
            id=building.id,
            kind=self._building_kind(building),
            name=building.name,
            symbol=getattr(type(building), "SYMBOL", "?"),
            position=building.position,
            hp=building.hp,
            max_hp=building.max_hp,
            cost=building.cost,
            power_supply=building.power_supply,
            power_draw=building.power_draw,
            connected_to_grid=building.connected_to_grid,
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
            effective_power_supply=building.effective_power_supply,
            splash_radius=(
                building.SPLASH_RADIUS if isinstance(building, CannonTower) else None
            ),
            splash_damage_ratio=(
                building.SPLASH_DAMAGE_RATIO
                if isinstance(building, CannonTower) else None
            ),
        )

    def _building_kind(self, building: Building) -> str:
        """Return the stable command/API key for a building instance."""
        for building_type, kind in BUILDING_KIND_BY_TYPE:
            if isinstance(building, building_type):
                return kind
        return type(building).__name__

    def _enemy_snapshots_by_position(self) -> dict[Position, tuple[EnemySnapshot, ...]]:
        """Group active enemies by their rendered route cell."""
        grouped: dict[Position, list[EnemySnapshot]] = {}
        for enemy in self.enemies:
            if not enemy.is_alive:
                continue

            world_position = enemy.world_position_on_route(self.grid_map.path)
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
                )
            )

        return {
            position: tuple(enemies)
            for position, enemies in grouped.items()
        }

    def _build_candidate(self, kind: str, position: Position) -> Building:
        """Create an uncommitted candidate without spending an entity ID.

        A type's FOOTPRINT determines its geometry. The anchor may be any
        small cell; it need not align to the former three-cell tile spacing.
        High-ground bonuses require the entire rectangle to be on high ground.
        """
        if not isinstance(kind, str):
            raise ValueError("Building kind must be a string.")
        if not isinstance(position, Position):
            raise ValueError("Building position must be a grid Position.")
        building = create_building(kind, self.next_building_id, position)
        if isinstance(building, Tower) and all(
            self.grid_map.is_high_ground(cell) for cell in building.occupied_cells()
        ):
            building.range += building.HIGH_GROUND_BONUS
        return building

    def _validate_placement(self, kind: str, building: Building) -> None:
        """Validate the full rectangle and command state before any mutation.

        Both preview_build() and build() use this rule source. A preview is
        advisory: build() rechecks current occupancy and gold to avoid relying
        on a result that may be stale after another player command.
        """
        if self.is_finished or self.core_hp <= 0:
            raise ValueError("Cannot build after the game has ended.")
        cells = building.occupied_cells()
        for cell in cells:
            if not self.grid_map.is_buildable(cell):
                raise ValueError(f"Position is not buildable: {cell}")
            if self.building_at(cell) is not None:
                raise ValueError(f"Position is already occupied: {cell}")
        if kind == "mine" and not all(self.grid_map.is_mine_site(cell) for cell in cells):
            raise ValueError("Mines must fit entirely within mine sites.")
        if kind != "mine" and any(self.grid_map.is_mine_site(cell) for cell in cells):
            raise ValueError("Only mines can be built on mine sites.")
        if self.gold < building.cost:
            raise ValueError(f"Not enough gold. Need {building.cost}, have {self.gold}.")

    def preview_build(self, kind: str, position: Position) -> BuildPreview:
        """Return footprint cells, validity and a rejection reason, without mutation.

        Illegal placement, insufficient gold and terminal games return an
        invalid preview. Unknown kinds or malformed arguments raise ValueError
        because no valid candidate geometry can be determined. Successful
        previews use an empty reason. The returned value is immutable.
        """
        building = self._build_candidate(kind, position)
        reason = ""
        try:
            self._validate_placement(kind, building)
        except ValueError as exc:
            reason = str(exc)
        return BuildPreview(
            kind=kind, position=position, width=building.width, height=building.height,
            occupied_cells=building.occupied_cells(), is_valid=not reason, reason=reason,
        )

    def build(self, kind: str, position: Position) -> Building:
        """Place a building using a top-left small-cell anchor.

        The whole footprint must be in bounds, unoccupied and outside roads,
        blocked ground and the core reservation. Mines must fit entirely in
        mine terrain; other buildings cannot overlap it. A tower receives the
        high-ground range bonus only when its entire footprint is on high ground.

        Raises ValueError for invalid kinds/positions, illegal placement,
        insufficient gold or a terminal game. Rejection and previewing never
        spend gold, allocate IDs or alter power. Success spends the cost,
        allocates one ID, adds the entity and refreshes power immediately.
        """
        building = self._build_candidate(kind, position)
        self._validate_placement(kind, building)
        self._next_id()
        self.gold -= building.cost
        self._add_building(building)
        self.recalculate_power()
        return building

    def repair_building(self, building_id: int) -> int:
        """Pay gold to instantly restore any existing building to full HP.

        Each missing HP costs one gold. DAY and NIGHT both allow repairs,
        including recovery of zero-HP non-core buildings left on the map.
        Returns the gold spent and refreshes power immediately on success.
        Overload timers, debt, and settlement service markers are unchanged.

        Raises ValueError for a non-positive/non-integer ID (including bool),
        missing building, full health, insufficient gold, destroyed core, or
        ended game. Rejected calls leave all state unchanged. Repairing a
        destroyed core cannot undo defeat, even before the next step().
        """
        if self.is_finished or self.core_hp <= 0:
            raise ValueError("Cannot repair after the game has ended.")
        if (
            isinstance(building_id, bool)
            or not isinstance(building_id, int)
            or building_id <= 0
        ):
            raise ValueError("Building ID must be a positive integer.")
        building = next(
            (building for building in self.buildings if building.id == building_id),
            None,
        )
        if building is None:
            raise ValueError(f"Building not found: {building_id}")
        cost = building.repair_cost
        if cost == 0:
            raise ValueError("Building is already at full health.")
        if self.gold < cost:
            raise ValueError(f"Not enough gold. Need {cost}, have {self.gold}.")

        self.gold -= cost
        building.repair()
        self.recalculate_power()
        return cost

    def sell_building(self, building_id: int) -> int:
        """Sell any non-core building and refund part of its build cost.

        The core cannot be sold. Selling removes the building immediately,
        refunds ``round(cost * SELL_REFUND_RATIO)`` gold, and recalculates power
        so downstream buildings may disconnect. Towers, mines, power plants,
        and power nodes are all sellable. Overload markers and debt are left
        unchanged. Unlike ``demolish_tower()``, this command refunds gold and
        rejects an ended game.

        Args:
            building_id: Positive integer ID of an existing non-core building.
                Booleans and non-integers are rejected.

        Returns:
            The gold refunded to the player.

        Raises:
            ValueError: The game has ended, the core is destroyed, the ID is
                not a positive integer, the building does not exist, or the
                target is the core. Rejected calls leave all state unchanged.
        """
        if self.is_finished or self.core_hp <= 0:
            raise ValueError("Cannot sell after the game has ended.")
        if (
            isinstance(building_id, bool)
            or not isinstance(building_id, int)
            or building_id <= 0
        ):
            raise ValueError("Building ID must be a positive integer.")
        building = next(
            (building for building in self.buildings if building.id == building_id),
            None,
        )
        if building is None:
            raise ValueError(f"Building not found: {building_id}")
        if isinstance(building, Core):
            raise ValueError("The core cannot be sold.")

        refund = round(building.cost * self.SELL_REFUND_RATIO)
        self.buildings = [
            building for building in self.buildings if building.id != building_id
        ]
        self.gold += refund
        self.recalculate_power()
        return refund

    def buy_wave_intel(self) -> str:
        """Spend 8 gold and return the current wave briefing.

        Returns:
            The current wave's `briefing`; returns `"No incoming wave."` when
            no waves remain.

        Raises:
            ValueError: The game has ended, the core is destroyed, or current
                gold is below the intel price. Rejected calls leave state
                unchanged.

        Note:
            When no waves remain in a non-terminal state, this returns
            `"No incoming wave."` without charging the intel price.
        """
        if self.is_finished or self.core_hp <= 0:
            raise ValueError("Cannot buy intel after the game has ended.")
        # Check availability before charging so an empty schedule is free.
        if self.wave_index >= len(self.waves):
            return "No incoming wave."

        cost = 8
        if self.gold < cost:
            raise ValueError("Not enough gold to buy intel.")
        self.gold -= cost
        return self.waves[self.wave_index].briefing

    def core_overdraft(self, gold_amount: int = 40) -> None:
        """Immediately add gold while increasing debt by 1.35x.

        Args:
            gold_amount: Positive integer gold gain, defaulting to 40.
                Booleans and floats are not accepted.

        Raises:
            ValueError: The game has ended, the core is destroyed, the amount
                is not a positive integer, or its debt calculation overflows.
                Rejected calls leave all state unchanged.

        Side effects:
            Increases `gold` and `debt`; interest is settled in `end_wave()`.
        """
        if self.is_finished or self.core_hp <= 0:
            raise ValueError("Cannot overdraft after the game has ended.")
        if (
            isinstance(gold_amount, bool)
            or not isinstance(gold_amount, int)
            or gold_amount <= 0
        ):
            raise ValueError("Overdraft amount must be a positive integer.")
        # Calculate before spending so overflow cannot leave a partial update.
        try:
            debt_increase = round(gold_amount * 1.35)
        except OverflowError:
            raise ValueError("Overdraft amount is too large to calculate debt.") from None

        self.gold += gold_amount
        self.debt += debt_increase

    def overload_tower(self, building_id: int, seconds: float = 8.0) -> None:
        """Temporarily overload a tower and register repair/debt costs.

        Args:
            building_id: Positive integer ID of the target tower, not a boolean.
            seconds: Finite positive int or float duration in logical seconds,
                defaulting to 8. Booleans are not accepted.

        Raises:
            ValueError: The game has ended, the core is destroyed, the ID or
                duration is invalid, or no tower with that ID exists.
                Rejected calls leave all state unchanged.

        Side effects:
            Extends the tower's overload timer, marks it for repair, and adds
            10 debt. Repeated calls still add debt each time, while the tower
            only keeps the longer overload window.
        """
        if self.is_finished or self.core_hp <= 0:
            raise ValueError("Cannot overload a tower after the game has ended.")
        if (
            isinstance(building_id, bool)
            or not isinstance(building_id, int)
            or building_id <= 0
        ):
            raise ValueError("Tower ID must be a positive integer.")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError("Overload duration must be a finite positive number.")
        try:
            duration = float(seconds)
        except OverflowError:
            raise ValueError("Overload duration must be a finite positive number.") from None
        if not isfinite(duration) or duration <= 0:
            raise ValueError("Overload duration must be a finite positive number.")

        tower = self.find_tower(building_id)
        tower.overload(duration)
        tower.needs_repair = True
        self.debt += 10

    def set_tower_target(self, tower_id: int, enemy_id: int) -> None:
        """Force one tower to attack a specific enemy before auto-selection.

        The manual target is honored only while it stays alive and inside the
        tower's range; otherwise the tower clears it and falls back to automatic
        target selection on its next attack.

        Args:
            tower_id: Positive integer ID of an existing tower. Booleans are
                rejected.
            enemy_id: Positive integer ID of an existing living enemy. Booleans
                are rejected.

        Raises:
            ValueError: The game has ended, the core is destroyed, either ID is
                not a positive integer, the tower does not exist, or the enemy
                does not exist or is already dead. Rejected calls leave all
                state unchanged.
        """
        if self.is_finished or self.core_hp <= 0:
            raise ValueError("Cannot set a target after the game has ended.")
        if (
            isinstance(tower_id, bool)
            or not isinstance(tower_id, int)
            or tower_id <= 0
        ):
            raise ValueError("Tower ID must be a positive integer.")
        if (
            isinstance(enemy_id, bool)
            or not isinstance(enemy_id, int)
            or enemy_id <= 0
        ):
            raise ValueError("Enemy ID must be a positive integer.")
        tower = self.find_tower(tower_id)
        enemy = next(
            (enemy for enemy in self.enemies if enemy.id == enemy_id and enemy.is_alive),
            None,
        )
        if enemy is None:
            raise ValueError(f"Enemy not found: {enemy_id}")
        tower.target_enemy_id = enemy_id

    def clear_tower_target(self, tower_id: int) -> None:
        """Remove a tower's manual target so it resumes automatic selection.

        Args:
            tower_id: Positive integer ID of an existing tower. Booleans are
                rejected.

        Raises:
            ValueError: The game has ended, the core is destroyed, the ID is not
                a positive integer, or the tower does not exist. Rejected calls
                leave all state unchanged.
        """
        if self.is_finished or self.core_hp <= 0:
            raise ValueError("Cannot clear a target after the game has ended.")
        if (
            isinstance(tower_id, bool)
            or not isinstance(tower_id, int)
            or tower_id <= 0
        ):
            raise ValueError("Tower ID must be a positive integer.")
        tower = self.find_tower(tower_id)
        tower.target_enemy_id = None

    def start_next_wave(self) -> None:
        """End the current DAY and start the upcoming NIGHT.

        This also starts the first night: initialization deliberately leaves
        the game in DAY with no runner. After later nights, end_wave() advances
        wave_index and returns to DAY. Starting never settles costs, advances
        the wave index, or generates enemies; the next step() does that.

        Raises:
            ValueError: The game has ended, the core is destroyed, the phase
                is not DAY, a runner already exists, or no waves remain.
                Rejected calls leave all state unchanged. Only final settlement
                grants victory.
        """
        if self.is_finished or self.core_hp <= 0:
            raise ValueError("Cannot start a wave after the game has ended.")
        if self.phase != GamePhase.DAY or self.wave_runner is not None:
            raise ValueError("Settle the current wave before starting the next wave.")
        if self.wave_index >= len(self.waves):
            raise ValueError("No waves remain to start.")
        self.wave_runner = WaveRunner(self.waves[self.wave_index])
        self.phase = GamePhase.NIGHT

    def end_wave(self) -> str:
        """Settle income, interest, and repairs, then advance the wave index.

        Returns:
            A settlement summary intended for the text interface.

        Raises:
            ValueError: The game has ended, the core is destroyed, there is no
                active wave, spawning is incomplete, or enemies remain.
                Rejected calls leave all state unchanged.

        Side effects:
            Mines produce gold at current efficiency, debt charges 12%
            interest, and each repair-marked building costs 5 gold. Repair
            markers are cleared, `wave_index` advances, and the runner is
            cleared. Other nights return to DAY for unlimited planning; the
            final wave's settlement records VICTORY. Defeat is handled by
            `step()` and cannot be settled. Wave settlement clears overload
            service markers but does not restore HP; use repair_building().
        """
        if self.is_finished or self.core_hp <= 0:
            raise ValueError("Cannot settle a wave after the game has ended.")
        if self.phase != GamePhase.NIGHT or self.wave_runner is None:
            raise ValueError("No active wave to settle.")
        if not self.waiting_for_next_wave:
            raise ValueError("Cannot settle until spawning is complete and no enemies remain.")

        mine_income = sum(
            building.collect_income()
            for building in self.buildings
            if isinstance(building, Mine)
        )
        interest = round(self.debt * 0.12)
        repair_cost = sum(5 for building in self.buildings if building.needs_repair)

        self.gold += mine_income
        self.gold -= interest
        self.gold -= repair_cost

        for building in self.buildings:
            # After costs are settled, repair state resets for the next wave.
            building.needs_repair = False

        self.wave_index += 1
        self.wave_runner = None

        if self.wave_index >= len(self.waves):
            self.phase = GamePhase.VICTORY
            self.result_message = "Victory. All waves cleared."
        else:
            # Settlement and starting are separate commands. This preserves
            # a planning window and prevents another night starting by itself.
            self.phase = GamePhase.DAY

        return (
            f"Wave ended. Mine income +{mine_income}, "
            f"interest -{interest}, repairs -{repair_cost}, gold {self.gold}."
        )

    def step(self, seconds: float) -> None:
        """Advance one NIGHT time step; freeze simulation during DAY.

        Args:
            seconds: Finite, non-negative logical seconds to advance. Zero is
                allowed so callers can process night events scheduled at zero.

        Raises:
            ValueError: If `seconds` is a boolean, not numeric, negative,
                non-finite, or too large to represent as a float. Rejected
                calls leave the game state unchanged.

        Order:
            Spawn due enemies first, recalculate power, run tower attacks,
            advance enemies, and finally let saboteurs attack power buildings. This
            lets towers respond to newly spawned enemies while node attacks use
            the enemies' updated positions.

        Side effects:
            Changes the shared logical clock, wave runner state, building
            cooldowns, enemy health and positions, gold, and core health. The
            exact same `seconds` delta is passed to every time-dependent
            subsystem, so the GameState clock remains the single simulation
            time source.

        DAY and finished games accept valid durations without advancing the
        clock, cooldowns, overload/slow timers, or spawning. Validate the input
        first so invalid durations still raise during planning or after a result.
        """
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError("Step duration must be a finite non-negative number.")
        try:
            delta = float(seconds)
        except OverflowError:
            raise ValueError("Step duration must be a finite non-negative number.") from None
        if not isfinite(delta) or delta < 0:
            raise ValueError("Step duration must be a finite non-negative number.")

        if self.is_finished:
            return

        # A destroyed core takes precedence over planning or further combat.
        # This also handles states constructed with zero starting health.
        if self.core_hp <= 0:
            self.core_hp = 0
            self.phase = GamePhase.DEFEAT
            self.result_message = "Defeat. The core was destroyed."
            return
        if self.phase == GamePhase.DAY:
            return

        # Advance the authoritative clock with the exact logical delta. The
        # previous integer rounding caused repeated 0.05-second steps to lose
        # time even though enemies and cooldowns were already using floats.
        self.elapsed_seconds += delta

        if self.wave_runner is not None:
            for enemy in self.wave_runner.step(delta):
                enemy.id = self._next_enemy_id()
                self.enemies.append(enemy)

        self.recalculate_power()
        self._towers_attack(delta)
        self._advance_enemies(delta)
        if self.core_hp > 0:
            self._enemies_attack_power_buildings(delta)
            self.recalculate_power()

        if self.core_hp <= 0:
            self.core_hp = 0
            self.phase = GamePhase.DEFEAT
            self.result_message = "Defeat. The core was destroyed."

    def recalculate_power(self) -> PowerReport:
        """Recalculate power and cache the latest summary report."""
        self.latest_power_report = self.power_grid.calculate(self.grid_map, self.buildings)
        return self.latest_power_report

    def building_at(self, position: Position) -> Building | None:
        """Return the first building at a coordinate, or `None` if empty.

        Any occupied small cell resolves to the same building, including
        cells other than its top-left anchor. Legal buildings never overlap.
        """
        for building in self.buildings:
            if building.occupies(position):
                return building
        return None

    def demolish_tower(self, building_id: int) -> Tower:
        """Remove an existing defense tower and refresh grid connectivity.

        The prototype does not refund construction cost. Mines, power
        infrastructure, and the core cannot be removed through this operation.
        """
        tower = self.find_tower(building_id)
        self.buildings = [building for building in self.buildings if building.id != building_id]
        self.recalculate_power()
        return tower

    def find_tower(self, building_id: int) -> Tower:
        """Find a tower by entity ID without matching non-tower buildings."""
        for building in self.buildings:
            if building.id == building_id and isinstance(building, Tower):
                return building
        raise ValueError(f"Tower not found: {building_id}")

    def _add_building(self, building: Building) -> None:
        """Append a building that has already passed external validation."""
        self.buildings.append(building)

    def _next_id(self) -> int:
        """Allocate a monotonically increasing building ID."""
        building_id = self.next_building_id
        self.next_building_id += 1
        return building_id

    def _next_enemy_id(self) -> int:
        """Allocate a monotonically increasing runtime enemy ID."""
        enemy_id = self.next_enemy_id
        self.next_enemy_id += 1
        return enemy_id

    def _towers_attack(self, seconds: float) -> None:
        """Tick tower timers, run available attacks, and settle kill rewards.

        Each tower can attack at most once per time step; this method does not
        replay extra attacks that would have occurred inside a large step.
        Rewards are paid immediately at the end of the attack phase, and dead
        enemies are removed here so they do not enter the movement phase.
        """
        for building in self.buildings:
            if not isinstance(building, Tower):
                continue

            building.tick_cooldown(seconds)
            if not building.can_attack():
                continue

            target = self._select_target(building)
            if target is None:
                continue

            damage = building.current_damage()
            target.take_damage(damage)
            if isinstance(building, CannonTower):
                self._apply_splash_damage(building, target, damage)
            if isinstance(building, SlowTower):
                target.apply_slow(2.0)

            building.reset_cooldown()

        defeated = [enemy for enemy in self.enemies if not enemy.is_alive]
        self.gold += sum(enemy.reward for enemy in defeated)
        self.enemies = [enemy for enemy in self.enemies if enemy.is_alive]

    def _apply_splash_damage(
        self, tower: CannonTower, primary: Enemy, damage: float
    ) -> None:
        """Damage other living enemies around the cannon's primary target.

        Splash is centered on the primary target's continuous route position
        and is not clipped to the tower's attack range. The primary target is
        excluded so it only receives its full direct hit, and armor is applied
        by `Enemy.take_damage()` for every secondary target.
        """
        origin = primary.world_position_on_route(self.grid_map.path)
        splash_damage = damage * tower.SPLASH_DAMAGE_RATIO
        for enemy in self.enemies:
            if enemy is primary or not enemy.is_alive:
                continue
            if world_distance(
                enemy.world_position_on_route(self.grid_map.path), origin
            ) <= tower.SPLASH_RADIUS:
                enemy.take_damage(splash_damage)

    def _select_target(self, tower: Tower) -> Enemy | None:
        """Select a target, preferring a valid manual target when set.

        A manual target from ``set_tower_target()`` wins while it stays alive
        and inside the tower's range. When it becomes invalid the tower clears
        it and falls back to the furthest-progressing living enemy within range.
        Ties in route progress prefer the enemy nearest to the tower center.

        Range starts at the building's geometric center and ends at the
        enemy's continuous centerline position. world_distance() is the single
        combat-metric boundary; changing it does not change grid adjacency or
        path traversal. Dead enemies await reward cleanup but cannot absorb
        another tower's attack during this same simulation step.
        """
        if tower.target_enemy_id is not None:
            forced = next(
                (
                    enemy for enemy in self.enemies
                    if enemy.id == tower.target_enemy_id
                    and enemy.is_alive
                    and world_distance(
                        tower.center, enemy.world_position_on_route(self.grid_map.path)
                    ) <= tower.range
                ),
                None,
            )
            if forced is not None:
                return forced
            # Drop a stale manual target so the tower can resume auto targeting.
            tower.target_enemy_id = None

        targets = [
            enemy for enemy in self.enemies
            if enemy.is_alive and world_distance(
                tower.center, enemy.world_position_on_route(self.grid_map.path)
            ) <= tower.range
        ]
        if not targets:
            return None

        best_progress = max(enemy.path_progress for enemy in targets)
        best_progress_targets = [
            enemy for enemy in targets if enemy.path_progress == best_progress
        ]
        if len(best_progress_targets) == 1:
            return best_progress_targets[0]
        return min(
            best_progress_targets,
            key=lambda enemy: world_distance(
                tower.center, enemy.world_position_on_route(self.grid_map.path)
            ),
        )

    def _advance_enemies(self, seconds: float) -> None:
        """Advance enemies and convert route-end arrivals into core damage."""
        escaped: list[Enemy] = []
        for enemy in self.enemies:
            enemy.advance(seconds)
            if enemy.has_reached_core(self.grid_map.path):
                escaped.append(enemy)

        for enemy in escaped:
            self._core.take_damage(enemy.damage_to_core)

        self.enemies = [enemy for enemy in self.enemies if enemy not in escaped]

    def _enemies_attack_power_buildings(self, seconds: float) -> None:
        """Let ready saboteurs damage power plants, then nearby power nodes.

        Saboteurs remain on the fixed route in this prototype. Their attack
        range uses the same Manhattan distance policy as tower targeting, and
        each saboteur can perform at most one building attack per simulation
        step. Within range, power plants take priority over power nodes, and
        the nearest building wins within the same priority. Destroyed power
        buildings remain on the map with zero HP but stop supplying or
        transmitting power during the following recalculation.
        """
        targets = [
            building
            for building in self.buildings
            if isinstance(building, (PowerPlant, PowerNode))
            and not building.is_destroyed
        ]
        for enemy in self.enemies:
            enemy.tick_attack_cooldown(seconds)

        if not targets:
            return

        for enemy in self.enemies:
            if not enemy.can_attack_buildings:
                continue

            enemy_position = enemy.world_position_on_route(self.grid_map.path)
            in_range = [
                building
                for building in targets
                if world_distance(enemy_position, building.center) <= enemy.attack_range
            ]
            if not in_range:
                continue

            target = min(
                in_range,
                key=lambda building: (
                    0 if isinstance(building, PowerPlant) else 1,
                    world_distance(enemy_position, building.center),
                ),
            )
            target.take_damage(enemy.attack_damage)
            enemy.reset_attack_cooldown()
            if target.is_destroyed:
                targets.remove(target)
                if not targets:
                    return

