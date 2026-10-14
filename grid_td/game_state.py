"""Game-state aggregate and core simulation loop.

`GameState` is the single runtime coordinator. It owns the map, gold/debt,
buildings, enemies, core health, wave progress, and result state. It exposes
operations for building, intel, overdraft, overload, wave settlement, and each
time step; `PowerGrid`, `WaveRunner`, `Building`, and `Enemy` provide the
local rules it calls. Read-only presentation code should use `snapshot()`
instead of reading mutable attributes directly.

Key state-flow boundaries:

* `build()` changes the building list and gold, then recalculates power.
* `step()` spawns enemies, recalculates power, runs tower attacks, then moves
  enemies.
* `end_wave()` settles income, interest, and repairs; `start_next_wave()`
  creates the next runner.

This module does not handle input devices or UI rendering. `TextRenderer`
should only read state from here. Add new gameplay operations as explicit
methods on this class before allowing presentation code to mutate lists or
resources directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
from grid_td.position import Position
from grid_td.power_grid import PowerGrid, PowerReport
from grid_td.waves import WaveRunner, create_demo_waves


@dataclass(frozen=True)
class PowerSnapshot:
    """GUI-safe copy of the latest power-grid summary."""

    connected_count: int  # Number of buildings reachable from the core grid.
    total_supply: int  # Connected power supply.
    total_demand: int  # Connected power demand.
    efficiency: float  # Shared connected-building efficiency multiplier.


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
    position: Position  # Occupied grid cell.
    hp: int  # Current prototype health.
    max_hp: int  # Maximum prototype health.
    cost: int  # Build cost for this building type.
    power_supply: int  # Power provided when connected.
    power_draw: int  # Power consumed when connected.
    connected_to_grid: bool  # Whether the latest power pass reached it.
    efficiency: float  # Latest work multiplier.
    needs_repair: bool  # Whether wave settlement should charge repair cost.
    range: int | None = None  # Tower range; `None` for non-towers.
    damage: float | None = None  # Tower base damage; `None` for non-towers.
    cooldown_remaining: float | None = None  # Tower cooldown; `None` for non-towers.
    is_overloaded: bool = False  # Tower overload flag; always false for non-towers.


@dataclass(frozen=True)
class EnemySnapshot:
    """Read-only display contract for one active enemy."""

    name: str  # Enemy type name.
    position: Position  # Current discrete route cell.
    hp: float  # Current health.
    max_hp: float  # Maximum health.
    speed: float  # Base movement speed before slow effects.
    damage_to_core: int  # Damage applied if this enemy reaches the core.
    reward: int  # Gold paid when defeated.
    path_progress: float  # Continuous progress along the route.
    is_slowed: bool  # Whether a slow effect is currently active.


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
    elapsed_seconds: int
    wave_index: int  # Zero-based index into the configured wave tuple.
    current_wave_name: str
    waiting_for_next_wave: bool
    is_finished: bool
    result_message: str
    power: PowerSnapshot


@dataclass(frozen=True)
class GameSnapshot:
    """Complete read-only presentation snapshot for one render frame."""

    width: int
    height: int
    status: GameStatus
    board: tuple[tuple[CellSnapshot, ...], ...]


BUILDING_KIND_BY_TYPE: tuple[tuple[type[Building], str], ...] = (
    (Core, "core"),
    (Mine, "mine"),
    (PowerPlant, "power_plant"),
    (PowerNode, "power_node"),
    (GunTower, "gun_tower"),
    (CannonTower, "cannon_tower"),
    (SlowTower, "slow_tower"),
)


@dataclass
class GameState:
    """Mutable state and public operation entry point for one game run."""

    grid_map: GridMap
    gold: int = 180  # Current spendable gold; build, intel, and settlement change it.
    debt: int = 0  # Debt from overdraft/overload; interest is charged at wave end.
    core_hp: int = 30  # Remaining core health; escaped enemies reduce it.
    elapsed_seconds: int = 0  # Display-oriented integer logical time from step().
    buildings: list[Building] = field(default_factory=list)  # Current building entities.
    enemies: list[Enemy] = field(default_factory=list)  # Living enemies on the board.

    def __post_init__(self) -> None:
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
        self.wave_runner: WaveRunner | None = WaveRunner(self.waves[0])
        self.next_building_id = 1
        self.result_message = ""
        self.latest_power_report = PowerReport(0, 0, 0, 1.0)
        self._add_building(Core(self._next_id(), self.grid_map.core_position))
        self.recalculate_power()

    @property
    def is_finished(self) -> bool:
        """Return whether a victory or defeat result has been recorded."""
        return bool(self.result_message)

    @property
    def waiting_for_next_wave(self) -> bool:
        """Return whether spawning is complete and no enemies remain.

        Both conditions must hold before `end_wave()` is allowed. Spawning
        completion alone cannot settle the wave early, or unbeaten enemies
        would be skipped.
        """
        if self.wave_runner is None:
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
        if position == self.grid_map.core_position:
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
            range=tower.range if tower is not None else None,
            damage=tower.damage if tower is not None else None,
            cooldown_remaining=tower.cooldown_remaining if tower is not None else None,
            is_overloaded=tower.is_overloaded if tower is not None else False,
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

            position = enemy.position_on_route(self.grid_map.route)
            grouped.setdefault(position, []).append(
                EnemySnapshot(
                    name=enemy.name,
                    position=position,
                    hp=enemy.hp,
                    max_hp=enemy.max_hp,
                    speed=enemy.speed,
                    damage_to_core=enemy.damage_to_core,
                    reward=enemy.reward,
                    path_progress=enemy.path_progress,
                    is_slowed=enemy.is_slowed,
                )
            )

        return {
            position: tuple(enemies)
            for position, enemies in grouped.items()
        }

    def build(self, kind: str, position: Position) -> Building:
        """Build at a position and update gold and power-grid state.

        Args:
            kind: Building key supported by `create_building()`.
            position: Target grid coordinate. Mines must use mine sites, and
                other buildings cannot occupy mine sites.

        Returns:
            The newly created `Building` subclass instance.

        Raises:
            ValueError: Position is out of bounds or not buildable, occupied,
                incompatible with mine-site rules, unknown by kind, or too
                expensive.

        Side effects:
            Spends build cost, appends the building, and immediately
            recalculates power. The current implementation allocates an ID
            before checking gold, so failed insufficient-gold attempts still
            consume an internal ID; callers should not rely on gapless IDs.
        """
        if not self.grid_map.is_buildable(position):
            raise ValueError(f"Position is not buildable: {position}")
        if self.building_at(position) is not None:
            raise ValueError(f"Position is already occupied: {position}")
        if kind == "mine" and not self.grid_map.is_mine_site(position):
            raise ValueError("Mines can only be built on mine sites.")
        if kind != "mine" and self.grid_map.is_mine_site(position):
            raise ValueError("Only mines can be built on mine sites.")

        building = create_building(
            kind=kind,
            building_id=self._next_id(),
            position=position,
            high_ground=self.grid_map.is_high_ground(position),
        )

        if self.gold < building.cost:
            raise ValueError(f"Not enough gold. Need {building.cost}, have {self.gold}.")

        self.gold -= building.cost
        self._add_building(building)
        self.recalculate_power()
        return building

    def buy_wave_intel(self) -> str:
        """Spend 8 gold and return the current wave briefing.

        Returns:
            The current wave's `briefing`; returns `"No incoming wave."` when
            no waves remain.

        Raises:
            ValueError: Current gold is below the intel price.

        Note:
            Gold is spent before checking whether a wave remains, so calling
            this after victory still costs 8 gold. That is current prototype
            behavior; changing it should update tests and UI expectations.
        """
        cost = 8
        if self.gold < cost:
            raise ValueError("Not enough gold to buy intel.")
        self.gold -= cost
        if self.wave_index >= len(self.waves):
            return "No incoming wave."
        return self.waves[self.wave_index].briefing

    def core_overdraft(self, gold_amount: int = 40) -> None:
        """Immediately add gold while increasing debt by 1.35x.

        Args:
            gold_amount: Gold gained from the overdraft, defaulting to 40. The
                current implementation does not validate sign, so gameplay
                callers should pass positive values only.

        Side effects:
            Increases `gold` and `debt`; interest is settled in `end_wave()`.
        """
        self.gold += gold_amount
        self.debt += round(gold_amount * 1.35)

    def overload_tower(self, building_id: int, seconds: float = 8.0) -> None:
        """Temporarily overload a tower and register repair/debt costs.

        Args:
            building_id: Building ID of the target tower.
            seconds: Logical seconds of overload duration, defaulting to 8.

        Raises:
            ValueError: No tower with the given ID exists.

        Side effects:
            Extends the tower's overload timer, marks it for repair, and adds
            10 debt. Repeated calls still add debt each time, while the tower
            only keeps the longer overload window.
        """
        tower = self.find_tower(building_id)
        tower.overload(seconds)
        tower.needs_repair = True
        self.debt += 10

    def start_next_wave(self) -> None:
        """Create a runner for the current `wave_index`, or mark victory.

        `wave_index` is advanced by `end_wave()`. This method only instantiates
        a runner for the current index, so the normal order is to settle the
        previous wave before starting the next one.
        """
        if self.wave_index >= len(self.waves):
            self.result_message = "Victory. All waves cleared."
            return
        self.wave_runner = WaveRunner(self.waves[self.wave_index])

    def end_wave(self) -> str:
        """Settle income, interest, and repairs, then advance the wave index.

        Returns:
            A settlement summary intended for the text interface.

        Side effects:
            Mines produce gold at current efficiency, debt charges 12%
            interest, and each repair-marked building costs 5 gold. Repair
            markers are cleared, `wave_index` advances, and the runner is
            cleared. If the core is destroyed or the final wave is complete,
            `result_message` is written. This does not restore building HP
            because `Building.hp` is not mutable in the current prototype.
        """
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

        if self.core_hp <= 0:
            self.result_message = "Defeat. The core was destroyed."
        elif self.wave_index >= len(self.waves):
            self.result_message = "Victory. All waves cleared."

        return (
            f"Wave ended. Mine income +{mine_income}, "
            f"interest -{interest}, repairs -{repair_cost}, gold {self.gold}."
        )

    def step(self, seconds: float) -> None:
        """Advance the game by one logical time step.

        Args:
            seconds: Float logical seconds to advance. Callers should pass a
                non-negative value.

        Order:
            Spawn due enemies first, recalculate power, run tower attacks, and
            finally advance enemies. This lets towers respond to newly spawned
            enemies in the same step, while enemies do not move before attacks.

        Side effects:
            Changes time, wave runner state, building cooldowns, enemy health
            and positions, gold, and core health. `elapsed_seconds` uses
            integer accumulation via `round(seconds)`, while waves, cooldowns,
            and movement still use the original float `seconds`.
        """
        if self.is_finished:
            return

        self.elapsed_seconds += round(seconds)

        if self.wave_runner is not None:
            self.enemies.extend(self.wave_runner.step(seconds))

        self.recalculate_power()
        self._towers_attack(seconds)
        self._advance_enemies(seconds)

        if self.core_hp <= 0:
            self.core_hp = 0
            self.result_message = "Defeat. The core was destroyed."

    def recalculate_power(self) -> PowerReport:
        """Recalculate power and cache the latest summary report."""
        self.latest_power_report = self.power_grid.calculate(self.grid_map, self.buildings)
        return self.latest_power_report

    def building_at(self, position: Position) -> Building | None:
        """Return the first building at a coordinate, or `None` if empty.

        The current implementation is a linear scan. The build entry point
        guarantees normal gameplay has no duplicate positions.
        """
        for building in self.buildings:
            if building.position == position:
                return building
        return None

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

            target.take_damage(building.current_damage())
            if isinstance(building, SlowTower):
                target.apply_slow(2.0)

            building.reset_cooldown()

        defeated = [enemy for enemy in self.enemies if not enemy.is_alive]
        self.gold += sum(enemy.reward for enemy in defeated)
        self.enemies = [enemy for enemy in self.enemies if enemy.is_alive]

    def _select_target(self, tower: Tower) -> Enemy | None:
        """Select the in-range enemy with the highest route progress.

        Range uses Manhattan distance between the tower coordinate and the
        enemy's current discrete route cell. Ties by progress have no extra
        ordering guarantee. This default policy matches the design intent of
        prioritizing enemies closest to the core.
        """
        targets = [
            enemy
            for enemy in self.enemies
            if tower.position.manhattan_distance(enemy.position_on_route(self.grid_map.route))
            <= tower.range
        ]
        if not targets:
            return None
        return max(targets, key=lambda enemy: enemy.path_progress)

    def _advance_enemies(self, seconds: float) -> None:
        """Advance enemies and convert route-end arrivals into core damage."""
        escaped: list[Enemy] = []
        for enemy in self.enemies:
            enemy.advance(seconds)
            if enemy.has_reached_core(self.grid_map.route):
                escaped.append(enemy)

        for enemy in escaped:
            self.core_hp -= enemy.damage_to_core

        self.enemies = [enemy for enemy in self.enemies if enemy not in escaped]

