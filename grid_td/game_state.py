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
    grid_map: GridMap
    gold: int = 180
    debt: int = 0
    core_hp: int = 30
    elapsed_seconds: int = 0
    buildings: list[Building] = field(default_factory=list)
    enemies: list[Enemy] = field(default_factory=list)

    def __post_init__(self) -> None:
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
        return bool(self.result_message)

    @property
    def waiting_for_next_wave(self) -> bool:
        if self.wave_runner is None:
            return False
        return self.wave_runner.is_complete and not self.enemies

    @property
    def current_wave_name(self) -> str:
        if self.wave_index >= len(self.waves):
            return "No more waves"
        return self.waves[self.wave_index].name

    def build(self, kind: str, position: Position) -> Building:
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
        cost = 8
        if self.gold < cost:
            raise ValueError("Not enough gold to buy intel.")
        self.gold -= cost
        if self.wave_index >= len(self.waves):
            return "No incoming wave."
        return self.waves[self.wave_index].briefing

    def core_overdraft(self, gold_amount: int = 40) -> None:
        self.gold += gold_amount
        self.debt += round(gold_amount * 1.35)

    def overload_tower(self, building_id: int, seconds: float = 8.0) -> None:
        tower = self.find_tower(building_id)
        tower.overload(seconds)
        tower.needs_repair = True
        self.debt += 10

    def start_next_wave(self) -> None:
        if self.wave_index >= len(self.waves):
            self.result_message = "Victory. All waves cleared."
            return
        self.wave_runner = WaveRunner(self.waves[self.wave_index])

    def end_wave(self) -> str:
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
        self.latest_power_report = self.power_grid.calculate(self.grid_map, self.buildings)
        return self.latest_power_report

    def building_at(self, position: Position) -> Building | None:
        for building in self.buildings:
            if building.position == position:
                return building
        return None

    def find_tower(self, building_id: int) -> Tower:
        for building in self.buildings:
            if building.id == building_id and isinstance(building, Tower):
                return building
        raise ValueError(f"Tower not found: {building_id}")

    def _add_building(self, building: Building) -> None:
        self.buildings.append(building)

    def _next_id(self) -> int:
        building_id = self.next_building_id
        self.next_building_id += 1
        return building_id

    def _towers_attack(self, seconds: float) -> None:
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
        escaped: list[Enemy] = []
        for enemy in self.enemies:
            enemy.advance(seconds)
            if enemy.has_reached_core(self.grid_map.route):
                escaped.append(enemy)

        for enemy in escaped:
            self.core_hp -= enemy.damage_to_core

        self.enemies = [enemy for enemy in self.enemies if enemy not in escaped]

