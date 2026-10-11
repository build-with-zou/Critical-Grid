from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from grid_td.position import Position


@dataclass
class Building:
    id: int
    name: str
    position: Position
    cost: int
    max_hp: int
    power_supply: int = 0
    power_draw: int = 0
    efficiency: float = 0.0
    connected_to_grid: bool = False
    needs_repair: bool = False

    @property
    def hp(self) -> int:
        return self.max_hp

    @property
    def is_power_source(self) -> bool:
        return self.power_supply > 0

    def can_transmit_power(self) -> bool:
        return self.connected_to_grid or self.is_power_source


@dataclass
class Core(Building):
    SYMBOL: ClassVar[str] = "C"

    def __init__(self, building_id: int, position: Position) -> None:
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
    SYMBOL: ClassVar[str] = "M"
    income: int = 12

    def __init__(self, building_id: int, position: Position) -> None:
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
        return round(self.income * self.efficiency)


@dataclass
class PowerPlant(Building):
    SYMBOL: ClassVar[str] = "P"

    def __init__(self, building_id: int, position: Position) -> None:
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
    SYMBOL: ClassVar[str] = "N"

    def __init__(self, building_id: int, position: Position) -> None:
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
    range: int = 2
    damage: float = 1.0
    cooldown_seconds: float = 1.0
    cooldown_remaining: float = 0.0
    overload_seconds_remaining: float = 0.0

    @property
    def is_overloaded(self) -> bool:
        return self.overload_seconds_remaining > 0

    def tick_cooldown(self, seconds: float) -> None:
        self.cooldown_remaining = max(0.0, self.cooldown_remaining - seconds)
        self.overload_seconds_remaining = max(0.0, self.overload_seconds_remaining - seconds)

    def can_attack(self) -> bool:
        return self.connected_to_grid and self.efficiency > 0 and self.cooldown_remaining <= 0

    def current_damage(self) -> float:
        overload_bonus = 1.75 if self.is_overloaded else 1.0
        return self.damage * self.efficiency * overload_bonus

    def attack_speed_multiplier(self) -> float:
        overload_bonus = 1.5 if self.is_overloaded else 1.0
        return max(0.1, self.efficiency * overload_bonus)

    def reset_cooldown(self) -> None:
        self.cooldown_remaining = self.cooldown_seconds / self.attack_speed_multiplier()

    def overload(self, seconds: float) -> None:
        self.overload_seconds_remaining = max(self.overload_seconds_remaining, seconds)


@dataclass
class GunTower(Tower):
    SYMBOL: ClassVar[str] = "G"

    def __init__(self, building_id: int, position: Position, high_ground: bool = False) -> None:
        super().__init__(
            id=building_id,
            name="Gun Tower",
            position=position,
            cost=30,
            max_hp=8,
            power_draw=3,
            range=3 if high_ground else 2,
            damage=4.0,
            cooldown_seconds=1.0,
        )


@dataclass
class CannonTower(Tower):
    SYMBOL: ClassVar[str] = "A"

    def __init__(self, building_id: int, position: Position, high_ground: bool = False) -> None:
        super().__init__(
            id=building_id,
            name="Cannon Tower",
            position=position,
            cost=45,
            max_hp=8,
            power_draw=5,
            range=3 if high_ground else 2,
            damage=8.0,
            cooldown_seconds=2.0,
        )


@dataclass
class SlowTower(Tower):
    SYMBOL: ClassVar[str] = "S"

    def __init__(self, building_id: int, position: Position, high_ground: bool = False) -> None:
        super().__init__(
            id=building_id,
            name="Slow Tower",
            position=position,
            cost=35,
            max_hp=8,
            power_draw=4,
            range=3 if high_ground else 2,
            damage=1.0,
            cooldown_seconds=1.5,
        )


def create_building(kind: str, building_id: int, position: Position, high_ground: bool = False) -> Building:
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

