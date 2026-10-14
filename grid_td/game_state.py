"""Game-state aggregate and core simulation loop.

`GameState` is the single runtime coordinator. It owns the map, gold/debt,
buildings, enemies, core health, wave progress, and result state. It exposes
operations for building, intel, overdraft, overload, wave settlement, and each
time step; `PowerGrid`, `WaveRunner`, `Building`, and `Enemy` provide the
local rules it calls.

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
    Core,
    Mine,
    SlowTower,
    Tower,
    create_building,
)
from grid_td.enemies import Enemy
from grid_td.map import GridMap
from grid_td.position import Position
from grid_td.power_grid import PowerGrid, PowerReport
from grid_td.waves import WaveRunner, create_demo_waves


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

