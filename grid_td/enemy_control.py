"""Enemy path assignment, saboteur targeting, and movement.

This module contains the coordinator logic that used to live on ``GameState``.
Functions operate on explicit map, building, and enemy collections, so they can
be unit-tested without constructing a full game. ``GameState`` keeps thin
wrappers for the methods used by existing tests.

Path geometry and breach planning stay in ``grid_td.pathing``; this module only
decides goals and applies the selected plan to enemies.
"""

from __future__ import annotations

from grid_td.buildings import Building, Core, PowerNode, PowerPlant
from grid_td.combat import (
    find_breach_target,
    find_target_building,
    in_breach_range,
    power_priority,
)
from grid_td.enemies import Enemy
from grid_td.map import GridMap
from grid_td.path import RoutePath
from grid_td.pathing import PathPlan, cells_within_range, find_path
from grid_td.position import WorldPosition, world_distance


def active_enemy_path(enemy: Enemy, fallback: RoutePath) -> RoutePath:
    """Return the enemy's assigned route or the shared fallback geometry."""
    return enemy.active_path(fallback)


def enemy_world_position(enemy: Enemy, fallback: RoutePath) -> WorldPosition:
    """Return the enemy's current continuous position on its active route."""
    return enemy.world_position_on_route(active_enemy_path(enemy, fallback))


def plan_to_building(
    grid_map: GridMap,
    buildings: list[Building],
    enemy: Enemy,
    current: WorldPosition,
    target: Building,
) -> PathPlan | None:
    """Plan to a walkable cell within the enemy's attack range of target."""
    goals = cells_within_range(grid_map, target.center, enemy.attack_range)
    if not goals:
        return None
    try:
        return find_path(
            grid_map,
            buildings,
            current.cell,
            enemy_speed=enemy.speed,
            breach_damage=enemy.breach_damage,
            goal_cells=goals,
        )
    except ValueError:
        return None


def plan_saboteur_target(
    grid_map: GridMap,
    buildings: list[Building],
    enemy: Enemy,
    current: WorldPosition,
) -> tuple[Building | None, PathPlan | None]:
    """Choose the nearest reachable plant, then node, for a saboteur."""
    power_buildings = [
        building
        for building in buildings
        if isinstance(building, (PowerPlant, PowerNode))
        and not building.is_destroyed
    ]
    for target_type in (PowerPlant, PowerNode):
        best: tuple[Building, PathPlan] | None = None
        for target in power_buildings:
            if not isinstance(target, target_type):
                continue
            plan = plan_to_building(grid_map, buildings, enemy, current, target)
            if plan is None:
                continue
            if best is None or plan.time_seconds < best[1].time_seconds:
                best = (target, plan)
        if best is not None:
            return best
    return None, None


def assign_enemy_path(
    grid_map: GridMap, buildings: list[Building], enemy: Enemy
) -> bool:
    """Plan and assign one enemy's route from its current cell.

    Saboteurs choose a reachable power plant, then node, before falling back to
    the core. A failed plan leaves the enemy stationary with a single-point
    route. Builders and repair commands reject footprints containing living
    enemies, so normal replans start from valid cells.
    """
    current = enemy_world_position(enemy, grid_map.path)
    plan: PathPlan | None = None
    target_id = None
    if enemy.targets_power_buildings:
        target, plan = plan_saboteur_target(grid_map, buildings, enemy, current)
        if target is not None:
            target_id = target.id

    if plan is None:
        try:
            plan = find_path(
                grid_map,
                buildings,
                current.cell,
                enemy_speed=enemy.speed,
                breach_damage=enemy.breach_damage,
            )
        except ValueError:
            plan = None

    enemy.path_progress = 0.0
    enemy.target_building_id = target_id
    if plan is None:
        enemy.route = RoutePath((current,))
        enemy.breach_target_id = None
        enemy.stalled = True
        return False

    enemy.route = plan.route
    enemy.breach_target_id = plan.breach_target_id
    enemy.stalled = False
    return True


def refresh_saboteur_targets(
    grid_map: GridMap, buildings: list[Building], enemies: list[Enemy]
) -> None:
    """Opportunistically switch saboteurs to higher-priority in-range targets.

    A higher-priority facility (plant over node) preempts an in-range target. If
    the current target is out of range, any in-range facility is preferred.
    Same-priority in-range targets are kept to avoid target oscillation.
    """
    alive = [
        building
        for building in buildings
        if isinstance(building, (PowerPlant, PowerNode))
        and not building.is_destroyed
    ]
    if not alive:
        return
    for enemy in enemies:
        if not enemy.is_alive or not enemy.targets_power_buildings:
            continue
        position = enemy_world_position(enemy, grid_map.path)
        in_range = [
            building
            for building in alive
            if world_distance(position, building.center) <= enemy.attack_range
        ]
        if not in_range:
            continue

        best = min(
            in_range,
            key=lambda building: (
                power_priority(building),
                world_distance(position, building.center),
                building.id,
            ),
        )
        current = find_target_building(enemy, buildings)
        if current is not None and in_breach_range(enemy, current, position):
            if power_priority(best) >= power_priority(current):
                continue

        if current is not None and current.id == best.id:
            continue

        enemy.target_building_id = best.id
        enemy.breach_target_id = None
        enemy.route = RoutePath((position,))
        enemy.path_progress = 0.0
        enemy.stalled = False


def replan_all_enemies(
    grid_map: GridMap, buildings: list[Building], enemies: list[Enemy]
) -> None:
    """Refresh every living enemy after a building or terrain change."""
    for enemy in enemies:
        if enemy.is_alive:
            assign_enemy_path(grid_map, buildings, enemy)


def enemy_in_footprint(
    building: Building, enemies: list[Enemy], fallback: RoutePath
) -> bool:
    """Return whether a living enemy currently occupies a building cell."""
    return any(
        enemy.is_alive
        and building.occupies(enemy_world_position(enemy, fallback).cell)
        for enemy in enemies
    )


def advance_enemies(
    grid_map: GridMap,
    buildings: list[Building],
    enemies: list[Enemy],
    seconds: float,
    core: Core,
) -> list[Enemy]:
    """Move enemies and return the list with escaped enemies removed.

    Enemies advance toward the core, a breach target, or infrastructure. Those
    that reach the core deal their core damage immediately.
    """
    escaped: list[Enemy] = []
    for enemy in enemies:
        if enemy.stalled:
            continue

        if enemy.breach_target_id is not None:
            target = find_breach_target(enemy, buildings)
            if target is None:
                assign_enemy_path(grid_map, buildings, enemy)
                continue
            if in_breach_range(
                enemy, target, enemy_world_position(enemy, grid_map.path)
            ):
                continue
            enemy.advance(seconds)
            continue

        if enemy.target_building_id is not None:
            target = find_target_building(enemy, buildings)
            if target is None:
                assign_enemy_path(grid_map, buildings, enemy)
                continue
            if in_breach_range(
                enemy, target, enemy_world_position(enemy, grid_map.path)
            ):
                continue
            enemy.advance(seconds)
            continue

        enemy.advance(seconds)
        if enemy.has_reached_core(active_enemy_path(enemy, grid_map.path)):
            escaped.append(enemy)

    for enemy in escaped:
        core.take_damage(enemy.damage_to_core)

    return [enemy for enemy in enemies if enemy not in escaped]
