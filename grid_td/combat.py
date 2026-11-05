"""Tower and enemy combat rules.

This module contains the state-mutating combat helpers that used to live on
``GameState``. Functions receive the current building and enemy lists plus a
``position_of`` callback, so they do not depend on the coordinator or on how
enemy routes are stored. ``GameState`` keeps thin wrappers for the helpers that
existing tests call directly.

The combat metric is still ``world_distance``; keep it centralized in
``grid_td.position`` when changing range rules.
"""

from __future__ import annotations

from collections.abc import Callable

from grid_td.buildings import (
    Building,
    CannonTower,
    Mine,
    PowerNode,
    PowerPlant,
    SlowTower,
    Tower,
)
from grid_td.enemies import Enemy
from grid_td.position import WorldPosition, world_distance

PositionOf = Callable[[Enemy], WorldPosition]
Distance = Callable[[WorldPosition, WorldPosition], float]


def power_priority(building: Building) -> int:
    """Rank plants before nodes for saboteur target selection."""
    return 0 if isinstance(building, PowerPlant) else 1


def alive_power_buildings(buildings: list[Building]) -> list[Building]:
    """Return living power plants and nodes for saboteur targeting."""
    return [
        building
        for building in buildings
        if isinstance(building, (PowerPlant, PowerNode))
        and not building.is_destroyed
    ]


def find_target_building(
    enemy: Enemy, buildings: list[Building]
) -> Building | None:
    """Resolve an enemy's infrastructure target if it is still alive."""
    if enemy.target_building_id is None:
        return None
    return next(
        (
            building
            for building in buildings
            if building.id == enemy.target_building_id
            and not building.is_destroyed
        ),
        None,
    )


def find_breach_target(
    enemy: Enemy, buildings: list[Building]
) -> Building | None:
    """Resolve an enemy's planned breach target if it is still alive."""
    if enemy.breach_target_id is None:
        return None
    return next(
        (
            building
            for building in buildings
            if building.id == enemy.breach_target_id
            and not building.is_destroyed
        ),
        None,
    )


def in_breach_range(
    enemy: Enemy, building: Building, position: WorldPosition
) -> bool:
    """Return whether the enemy at ``position`` can attack the building."""
    return (
        enemy.attack_range > 0
        and world_distance(position, building.center) <= enemy.attack_range
    )


def select_tower_target(
    tower: Tower,
    enemies: list[Enemy],
    position_of: PositionOf,
    distance: Distance = world_distance,
) -> Enemy | None:
    """Select a target, preferring a valid manual target when set.

    A manual target from ``set_tower_target()`` wins while it stays alive and
    inside the tower's range. When it becomes invalid the tower clears it and
    falls back to the furthest-progressing living enemy within range. Ties in
    route progress prefer the enemy nearest to the tower center.

    ``distance`` is injectable so callers can keep a single metric boundary for
    tests and future metric changes.
    """
    if tower.target_enemy_id is not None:
        forced = next(
            (
                enemy for enemy in enemies
                if enemy.id == tower.target_enemy_id
                and enemy.is_alive
                and distance(tower.center, position_of(enemy)) <= tower.range
            ),
            None,
        )
        if forced is not None:
            return forced
        # Drop a stale manual target so the tower can resume auto targeting.
        tower.target_enemy_id = None

    targets = [
        enemy for enemy in enemies
        if enemy.is_alive
        and distance(tower.center, position_of(enemy)) <= tower.range
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
        key=lambda enemy: distance(tower.center, position_of(enemy)),
    )


def apply_splash_damage(
    tower: CannonTower,
    primary: Enemy,
    enemies: list[Enemy],
    position_of: PositionOf,
    damage: float,
    distance: Distance = world_distance,
) -> None:
    """Damage other living enemies around the cannon's primary target.

    Splash is centered on the primary target's continuous route position and is
    not clipped to the tower's attack range. The primary target is excluded so
    it only receives its full direct hit, and armor is applied by
    ``Enemy.take_damage()`` for every secondary target.
    """
    origin = position_of(primary)
    splash_damage = damage * tower.SPLASH_DAMAGE_RATIO
    for enemy in enemies:
        if enemy is primary or not enemy.is_alive:
            continue
        if distance(position_of(enemy), origin) <= tower.SPLASH_RADIUS:
            enemy.take_damage(splash_damage)


def run_tower_attacks(
    buildings: list[Building],
    enemies: list[Enemy],
    position_of: PositionOf,
    seconds: float,
    distance: Distance = world_distance,
) -> list[Enemy]:
    """Tick tower timers, run available attacks, and return defeated enemies.

    Each tower can attack at most once per time step; this function does not
    replay extra attacks that would have occurred inside a large step. The
    caller pays rewards and removes the returned dead enemies.
    """
    for building in buildings:
        if not isinstance(building, Tower):
            continue

        building.tick_cooldown(seconds)
        if not building.can_attack():
            continue

        target = select_tower_target(building, enemies, position_of, distance)
        if target is None:
            continue

        damage = building.current_damage()
        target.take_damage(damage)
        if isinstance(building, CannonTower):
            apply_splash_damage(
                building, target, enemies, position_of, damage, distance
            )
        if isinstance(building, SlowTower):
            target.apply_slow(2.0)

        building.reset_cooldown()

    return [enemy for enemy in enemies if not enemy.is_alive]


def enemy_attack_candidates(
    enemy: Enemy, buildings: list[Building]
) -> list[Building]:
    """Return living buildings this enemy type is allowed to attack."""
    if enemy.targets_power_buildings:
        kinds = (PowerPlant, PowerNode)
    else:
        kinds = (Mine, Tower)
    return [
        building
        for building in buildings
        if isinstance(building, kinds) and not building.is_destroyed
    ]


def select_enemy_building_target(
    enemy: Enemy, buildings: list[Building], position: WorldPosition
) -> Building | None:
    """Choose an in-range target using stable type, distance, and ID rules."""
    in_range = [
        building
        for building in enemy_attack_candidates(enemy, buildings)
        if world_distance(position, building.center) <= enemy.attack_range
    ]
    if not in_range:
        return None
    if enemy.targets_power_buildings:
        return min(
            in_range,
            key=lambda building: (
                0 if isinstance(building, PowerPlant) else 1,
                world_distance(position, building.center),
                building.id,
            ),
        )
    return min(
        in_range,
        key=lambda building: (
            world_distance(position, building.center),
            building.id,
        ),
    )


def resolve_enemy_attacks(
    enemies: list[Enemy],
    buildings: list[Building],
    position_of: PositionOf,
    seconds: float,
) -> bool:
    """Resolve breach attacks and active attacks on enemy-specific targets.

    Breach hits deal one point per ``breach_cooldown_seconds``, preserving the
    configured damage-per-second differences. A breaching enemy does not also
    perform a normal building attack in the same step. Saboteurs target power
    facilities, while other enemy types target mines and towers.

    Returns:
        Whether any building was destroyed during this resolution. The caller
        should refresh enemy paths in that case.
    """
    for enemy in enemies:
        enemy.tick_attack_cooldown(seconds)
        enemy.tick_breach_cooldown(seconds)

    destroyed_any = False
    breaching_ids: set[int] = set()
    for enemy in enemies:
        target = find_breach_target(enemy, buildings)
        if target is None:
            continue
        breaching_ids.add(enemy.id)
        if not enemy.can_breach or not in_breach_range(
            enemy, target, position_of(enemy)
        ):
            continue
        target.take_damage(1)
        enemy.reset_breach_cooldown()
        if target.is_destroyed:
            destroyed_any = True

    targeted_ids: set[int] = set()
    for enemy in enemies:
        if enemy.id in breaching_ids or not enemy.can_attack_buildings:
            continue
        target = find_target_building(enemy, buildings)
        if target is None:
            enemy.target_building_id = None
            continue
        if target not in enemy_attack_candidates(enemy, buildings):
            enemy.target_building_id = None
            continue
        if not in_breach_range(enemy, target, position_of(enemy)):
            if not enemy.targets_power_buildings:
                enemy.target_building_id = None
            continue
        target.take_damage(enemy.attack_damage)
        enemy.reset_attack_cooldown()
        targeted_ids.add(enemy.id)
        if target.is_destroyed:
            destroyed_any = True

    for enemy in enemies:
        if enemy.id in breaching_ids or enemy.id in targeted_ids:
            continue
        if not enemy.can_attack_buildings:
            continue

        target = select_enemy_building_target(
            enemy, buildings, position_of(enemy)
        )
        if target is None:
            continue
        enemy.target_building_id = target.id
        target.take_damage(enemy.attack_damage)
        enemy.reset_attack_cooldown()
        if target.is_destroyed:
            destroyed_any = True

    return destroyed_any
