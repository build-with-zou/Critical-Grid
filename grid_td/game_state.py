"""Game-state aggregate and core simulation loop.

`GameState` is the single runtime coordinator. It owns the map, gold/debt,
buildings, enemies, core health, wave progress, and result state. It exposes
operations for building, selling, repair, targeting, intel, overdraft,
overload, wave settlement, and each time step. Combat, enemy path assignment,
settlement arithmetic, and snapshot construction live in `combat.py`,
`enemy_control.py`, `economy.py`, `snapshots.py`, and `snapshot_builder.py`;
this class keeps the public commands and the simulation order. Read-only
presentation code should use `snapshot()` instead of reading mutable
attributes directly.

Key state-flow boundaries:

* `build()` changes the building list and gold, then recalculates power.
* New games start in DAY with no active wave runner.
* `start_next_wave()` ends planning and creates a fresh NIGHT runner.
* During NIGHT, `step()` spawns enemies, recalculates power, runs tower
  attacks, moves enemies, then resolves enemy attacks on buildings. During DAY
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
from math import isfinite
from typing import TYPE_CHECKING, ClassVar

from grid_td import combat, enemy_control
from grid_td.buildings import (
    Building,
    Core,
    PowerPriority,
    Tower,
    create_building,
)
from grid_td.economy import calculate_settlement, format_settlement
from grid_td.enemies import Enemy
from grid_td.intel import WaveIntel, build_wave_intel, preview_wave_intel
from grid_td.map import GridMap
from grid_td.path import RoutePath
from grid_td.position import (
    DISTANCE_METRIC,
    Position,
    WorldPosition,
    world_distance,
)
from grid_td.power_grid import PowerGrid, PowerReport
from grid_td.snapshot_builder import SnapshotBuilder
from grid_td.snapshots import (
    BuildPreview,
    BuildingSnapshot as BuildingSnapshot,
    CellSnapshot,
    EnemySnapshot as EnemySnapshot,
    GamePhase,
    GameSnapshot,
    GameStatus,
    PowerSnapshot,
)
from grid_td.waves import Wave, WaveRunner, create_demo_waves

if TYPE_CHECKING:
    from grid_td.levels import LevelDefinition


@dataclass(init=False)
class GameState:
    """Mutable state and public operation entry point for one game run."""

    # Fraction of build cost refunded by sell_building(); the core is never sold.
    SELL_REFUND_RATIO: ClassVar[float] = 0.7

    grid_map: GridMap
    intel_price: int = 8  # Detailed-intel price, normally set from the level.
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
        waves: tuple[Wave, ...] | None = None,
        intel_price: int = 8,
    ) -> None:
        """Keep the existing constructor while storing core HP on the core.

        A custom initializer lets core_hp remain a compatibility property
        rather than a second mutable health counter. Callers may inject a
        level-specific wave tuple; omitting it keeps the demo schedule.
        ``intel_price`` is the once-per-wave detailed intel cost.
        """
        if (
            isinstance(intel_price, bool)
            or not isinstance(intel_price, int)
            or intel_price < 0
        ):
            raise ValueError("Intel price must be a non-negative integer.")
        self.grid_map = grid_map
        self.gold = gold
        self.debt = debt
        self.elapsed_seconds = elapsed_seconds
        self.buildings = buildings if buildings is not None else []
        self.enemies = enemies if enemies is not None else []
        self.waves = waves if waves is not None else create_demo_waves()
        self.intel_price = intel_price
        self.phase = GamePhase.DAY
        self.__post_init__(core_hp)

    def __post_init__(self, core_hp: int = 30) -> None:
        """Initialize runtime collaborators, wave state, the core, and power.

        Attributes such as `power_grid`, `waves`, and `wave_index` are runtime
        state. The core is added to the building list here, so a passed-in
        `buildings` list is extended in place.
        """
        self.power_grid = PowerGrid()
        self.wave_index = 0
        # The upcoming wave index exists during planning, but its clock must
        # not start until the player explicitly ends the day.
        self.wave_runner: WaveRunner | None = None
        self.next_building_id = 1
        self.next_enemy_id = 1
        self.result_message = ""
        self.latest_power_report = PowerReport(0, 0, 0, 1.0)
        # Intel is static per wave; cache it lazily and rebuild if callers
        # replace the public `waves` tuple (existing tests do this).
        self._unlocked_intel_waves: set[int] = set()
        self._intel_cache_source: tuple[Wave, ...] | None = None
        self._wave_intel_full: tuple[WaveIntel, ...] = ()
        self._wave_intel_preview: tuple[WaveIntel, ...] = ()
        # Static board layers are cached per map object; replacing grid_map
        # creates a new builder on the next snapshot request.
        self._snapshot_builder_source: GridMap | None = None
        self._snapshot_builder_value: SnapshotBuilder | None = None
        core = Core(self._next_id(), self.grid_map.core_position)
        self._core = core
        # Custom starting health may exceed the default in scenarios/tests.
        core.max_hp = max(core.max_hp, core_hp)
        self.core_hp = core_hp
        # Match the map's reservation, including custom core dimensions.
        core.footprint = self.grid_map.core_footprint
        self._add_building(core)
        self.recalculate_power()

    @classmethod
    def from_level(cls, level: "LevelDefinition") -> "GameState":
        """Create a game using a level's map, waves, and starting resources."""
        return cls(
            level.grid_map,
            gold=level.starting_gold,
            core_hp=level.starting_core_hp,
            waves=level.waves,
            intel_price=level.intel_price,
        )

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

    def _ensure_intel_cache(self) -> None:
        """Rebuild derived intel when the public wave tuple changes.

        Waves are static during normal play, but tests and scenarios may
        replace ``game.waves`` directly. Identity invalidation keeps cached
        intel consistent without exposing mutation of private state.
        """
        if self._intel_cache_source is self.waves:
            return
        full = tuple(
            build_wave_intel(
                wave,
                index,
                self.grid_map.spawn_entrances,
                self.grid_map.path.points,
                self.grid_map.path.length,
            )
            for index, wave in enumerate(self.waves)
        )
        self._wave_intel_full = full
        self._wave_intel_preview = tuple(
            preview_wave_intel(intel) for intel in full
        )
        self._intel_cache_source = self.waves

    def wave_intel(self) -> WaveIntel | None:
        """Return free coarse intel for the current wave, if one exists.

        Free intel never spends gold and never exposes detailed counts,
        timing, or route geometry. It is safe for presentation to read every
        frame.
        """
        self._ensure_intel_cache()
        if self.wave_index >= len(self._wave_intel_preview):
            return None
        return self._wave_intel_preview[self.wave_index]

    def detailed_wave_intel(self) -> WaveIntel | None:
        """Return purchased detailed intel, or None before the wave unlock.

        Unlocks are permanent per wave and are charged by buy_wave_intel().
        Indices already unlocked are never charged again.
        """
        self._ensure_intel_cache()
        if self.wave_index not in self._unlocked_intel_waves:
            return None
        if self.wave_index >= len(self._wave_intel_full):
            return None
        return self._wave_intel_full[self.wave_index]

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
            entrances=self.grid_map.spawn_entrances,
        )

    def _snapshot_builder(self) -> SnapshotBuilder:
        """Return a builder that matches the current map object.

        Static map layers are cached on the builder. Tests may replace
        ``grid_map`` with a new frozen map via ``dataclasses.replace``; comparing
        object identity invalidates the old caches without requiring a public
        invalidation command.
        """
        if self._snapshot_builder_source is not self.grid_map:
            self._snapshot_builder_value = SnapshotBuilder(self.grid_map)
            self._snapshot_builder_source = self.grid_map
        builder = self._snapshot_builder_value
        assert builder is not None
        return builder

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
            free_intel=self.wave_intel(),
            detailed_intel=self.detailed_wave_intel(),
            intel_price=self.intel_price,
            power=PowerSnapshot(
                connected_count=report.connected_count,
                total_supply=report.total_supply,
                total_demand=report.total_demand,
                efficiency=report.efficiency,
            ),
        )

    def board_snapshot(self) -> tuple[tuple[CellSnapshot, ...], ...]:
        """Return a row-major immutable snapshot of the whole board."""
        return self._snapshot_builder().board(self.buildings, self.enemies)

    def cell_snapshot(self, position: Position) -> CellSnapshot:
        """Return a read-only snapshot for one in-bounds map cell.

        Raises:
            ValueError: The requested position is outside the map.
        """
        if not self.grid_map.in_bounds(position):
            raise ValueError(f"Position is out of bounds: {position}")
        return self._snapshot_builder().cell(position, self.buildings, self.enemies)

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
        if self._enemy_in_footprint(building):
            raise ValueError("A living enemy occupies the building footprint.")
        if kind == "mine" and not all(self.grid_map.is_mine_site(cell) for cell in cells):
            raise ValueError("Mines must fit entirely within mine sites.")
        if kind != "mine" and any(self.grid_map.is_mine_site(cell) for cell in cells):
            raise ValueError("Only mines can be built on mine sites.")
        if self.gold < building.cost:
            raise ValueError(f"Not enough gold. Need {building.cost}, have {self.gold}.")

    def preview_build(self, kind: str, position: Position) -> BuildPreview:
        """Return placement validity and authoritative potential ranges without mutation.

        Illegal placement, insufficient gold and terminal games return an
        invalid preview. Unknown kinds or malformed arguments raise ValueError
        because no valid candidate geometry can be determined. Successful
        previews use an empty reason. Ranges remain available for invalid
        positions so the GUI can explain a rejected placement. Tower range
        uses the same candidate as build(), and transmission reach uses this
        game's configured grid radius. The returned value is immutable.
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
            center=building.center,
            attack_range=building.range if isinstance(building, Tower) else None,
            power_radius=self.power_grid.connection_radius if building.TRANSMITS_POWER else None,
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
        self._replan_all_enemies()
        return building

    def set_power_priority(
        self, building_id: int, priority: PowerPriority | str
    ) -> None:
        """Set the supply-allocation tier for a connected consumer.

        Priority changes are available during both DAY and NIGHT. Sources,
        relays, and the core have no power demand, so assigning them a tier is
        rejected instead of creating a setting with no observable effect.
        """
        if self.is_finished or self.core_hp <= 0:
            raise ValueError("Cannot change power priority after the game has ended.")
        if (
            isinstance(building_id, bool)
            or not isinstance(building_id, int)
            or building_id <= 0
        ):
            raise ValueError("Building ID must be a positive integer.")
        building = next(
            (candidate for candidate in self.buildings if candidate.id == building_id),
            None,
        )
        if building is None:
            raise ValueError(f"Building not found: {building_id}")
        if building.power_draw <= 0:
            raise ValueError("Only power-consuming buildings have a priority.")
        try:
            selected = priority if isinstance(priority, PowerPriority) else PowerPriority(priority)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Unknown power priority: {priority}") from exc
        building.power_priority = selected
        self.recalculate_power()

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
        if self._enemy_in_footprint(building):
            raise ValueError("A living enemy occupies the building footprint.")
        cost = building.repair_cost
        if cost == 0:
            raise ValueError("Building is already at full health.")
        if self.gold < cost:
            raise ValueError(f"Not enough gold. Need {cost}, have {self.gold}.")

        was_destroyed = building.is_destroyed
        self.gold -= cost
        building.repair()
        self.recalculate_power()
        if was_destroyed:
            self._replan_all_enemies()
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
        self._replan_all_enemies()
        return refund

    def buy_wave_intel(self) -> str:
        """Unlock detailed intel for the current wave and return its briefing.

        The string return preserves the existing GUI/text contract. Structured
        details become available through ``detailed_wave_intel()`` and
        ``snapshot().status.detailed_intel`` after the first successful call.

        Returns:
            The current wave's `briefing`; returns `"No incoming wave."` when
            no waves remain.

        Raises:
            ValueError: The game has ended, the core is destroyed, or current
                gold is below ``intel_price``. Rejected calls leave state
                unchanged.

        Note:
            Unlocks are permanent per wave. Calling this again for the same
            wave returns the briefing without charging gold. When no waves
            remain in a non-terminal state, it returns ``"No incoming wave."``
            without charging.
        """
        if self.is_finished or self.core_hp <= 0:
            raise ValueError("Cannot buy intel after the game has ended.")
        # Check availability before charging so an empty schedule is free.
        if self.wave_index >= len(self.waves):
            return "No incoming wave."

        briefing = self.waves[self.wave_index].briefing
        if self.wave_index in self._unlocked_intel_waves:
            return briefing

        if self.gold < self.intel_price:
            raise ValueError("Not enough gold to buy intel.")
        self.gold -= self.intel_price
        self._unlocked_intel_waves.add(self.wave_index)
        return briefing

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
                is not DAY, a runner already exists, no waves remain, or a
                spawn group references an invalid entrance. Rejected calls
                leave all state unchanged. Only final settlement grants
                victory.
        """
        if self.is_finished or self.core_hp <= 0:
            raise ValueError("Cannot start a wave after the game has ended.")
        if self.phase != GamePhase.DAY or self.wave_runner is not None:
            raise ValueError("Settle the current wave before starting the next wave.")
        if self.wave_index >= len(self.waves):
            raise ValueError("No waves remain to start.")
        wave = self.waves[self.wave_index]
        entrance_count = len(self.grid_map.spawn_entrances)
        for group in wave.groups:
            if (
                isinstance(group.entrance, bool)
                or not isinstance(group.entrance, int)
                or group.entrance < 0
                or group.entrance >= entrance_count
            ):
                raise ValueError(
                    f"Wave group entrance must be between 0 and {entrance_count - 1}."
                )
        self.wave_runner = WaveRunner(wave)
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

        settlement = calculate_settlement(self.buildings, self.debt)
        self.gold += settlement.net_gold

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

        return format_settlement(settlement, self.gold)

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
            advance enemies, and finally resolve enemy attacks on buildings.
            This lets towers respond to newly spawned enemies while building
            attacks use the enemies' updated positions.

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
                entrance = self.grid_map.spawn_entrances[enemy.entrance_index]
                enemy.route = RoutePath((entrance.center,))
                enemy.path_progress = 0.0
                self.enemies.append(enemy)
                self._assign_enemy_path(enemy)

        self.recalculate_power()
        self._towers_attack(delta)
        self._refresh_saboteur_targets()
        self._advance_enemies(delta)
        if self.core_hp > 0:
            self._enemies_attack_buildings(delta)
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
        self._replan_all_enemies()
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

    def _active_enemy_path(self, enemy: Enemy) -> RoutePath:
        """Return the enemy's assigned route or the shared prototype fallback."""
        return enemy_control.active_enemy_path(enemy, self.grid_map.path)

    def _enemy_world_position(self, enemy: Enemy) -> WorldPosition:
        """Return the enemy's current continuous position on its active route."""
        return enemy_control.enemy_world_position(enemy, self.grid_map.path)

    def _assign_enemy_path(self, enemy: Enemy) -> bool:
        """Plan and assign one enemy's route from its current cell."""
        return enemy_control.assign_enemy_path(
            self.grid_map, self.buildings, enemy
        )

    def _refresh_saboteur_targets(self) -> None:
        """Switch saboteurs to higher-priority in-range targets when useful."""
        enemy_control.refresh_saboteur_targets(
            self.grid_map, self.buildings, self.enemies
        )

    def _replan_all_enemies(self) -> None:
        """Refresh every living enemy after a building or terrain change."""
        enemy_control.replan_all_enemies(
            self.grid_map, self.buildings, self.enemies
        )

    def _enemy_in_footprint(self, building: Building) -> bool:
        """Return whether a living enemy currently occupies a building cell."""
        return enemy_control.enemy_in_footprint(
            building, self.enemies, self.grid_map.path
        )

    def _towers_attack(self, seconds: float) -> None:
        """Tick tower timers, run available attacks, and settle kill rewards.

        Each tower can attack at most once per time step; this method does not
        replay extra attacks that would have occurred inside a large step.
        Rewards are paid immediately at the end of the attack phase, and dead
        enemies are removed here so they do not enter the movement phase.
        """
        defeated = combat.run_tower_attacks(
            self.buildings,
            self.enemies,
            self._enemy_world_position,
            seconds,
            world_distance,
        )
        self.gold += sum(enemy.reward for enemy in defeated)
        self.enemies = [enemy for enemy in self.enemies if enemy.is_alive]

    def _select_target(self, tower: Tower) -> Enemy | None:
        """Select a target, preferring a valid manual target when set."""
        return combat.select_tower_target(
            tower, self.enemies, self._enemy_world_position, world_distance
        )

    def _advance_enemies(self, seconds: float) -> None:
        """Move enemies toward the core, a breach target, or infrastructure."""
        self.enemies = enemy_control.advance_enemies(
            self.grid_map,
            self.buildings,
            self.enemies,
            seconds,
            self._core,
        )

    def _enemies_attack_buildings(self, seconds: float) -> None:
        """Resolve breach and building attacks, then refresh paths if needed."""
        if combat.resolve_enemy_attacks(
            self.enemies,
            self.buildings,
            self._enemy_world_position,
            seconds,
        ):
            self._replan_all_enemies()

