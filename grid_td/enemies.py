from __future__ import annotations

from dataclasses import dataclass

from grid_td.position import Position


@dataclass
class Enemy:
    name: str
    max_hp: float
    speed: float
    damage_to_core: int
    reward: int
    path_progress: float = 0.0
    hp: float = 0.0
    slow_seconds_remaining: float = 0.0

    def __post_init__(self) -> None:
        if self.hp <= 0:
            self.hp = self.max_hp

    @property
    def is_alive(self) -> bool:
        return self.hp > 0

    @property
    def is_slowed(self) -> bool:
        return self.slow_seconds_remaining > 0

    def current_speed(self) -> float:
        return self.speed * (0.55 if self.is_slowed else 1.0)

    def take_damage(self, amount: float) -> None:
        self.hp = max(0.0, self.hp - amount)

    def apply_slow(self, seconds: float) -> None:
        self.slow_seconds_remaining = max(self.slow_seconds_remaining, seconds)

    def advance(self, seconds: float) -> None:
        self.path_progress += self.current_speed() * seconds
        self.slow_seconds_remaining = max(0.0, self.slow_seconds_remaining - seconds)

    def position_on_route(self, route: tuple[Position, ...]) -> Position:
        route_index = min(int(self.path_progress), len(route) - 1)
        return route[route_index]

    def has_reached_core(self, route: tuple[Position, ...]) -> bool:
        return self.path_progress >= len(route) - 1


def create_enemy(kind: str) -> Enemy:
    templates = {
        "basic": Enemy("Basic", max_hp=10, speed=0.75, damage_to_core=1, reward=4),
        "fast": Enemy("Fast", max_hp=7, speed=1.25, damage_to_core=1, reward=5),
        "armored": Enemy("Armored", max_hp=24, speed=0.45, damage_to_core=2, reward=8),
        "saboteur": Enemy("Saboteur", max_hp=14, speed=0.85, damage_to_core=2, reward=7),
    }

    try:
        template = templates[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown enemy kind: {kind}") from exc

    return Enemy(
        name=template.name,
        max_hp=template.max_hp,
        speed=template.speed,
        damage_to_core=template.damage_to_core,
        reward=template.reward,
    )

