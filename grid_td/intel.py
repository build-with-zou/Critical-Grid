"""Derived wave intelligence shared by the core and presentation layers.

Intel is a read-only projection of a level's wave schedule. Counts, spawn
order, entrances, and timing come from ``SpawnGroup`` values, so level authors
do not repeat them in TOML. Optional ``Wave.threat`` metadata can override the
derived threat tier; everything else is computed here.

The module has two levels of detail:

* Free/preview intel exposes enemy kinds, traits, threat direction, and a
  coarse threat tier. It never includes exact counts or timing.
* Detailed intel adds group totals, spawn timeline, entrance assignments,
  exact spawn windows, route geometry, and an approximate duration.

Estimated duration uses the map's primary route length and enemy base speed.
It intentionally ignores towers, slowing, and dynamic re-pathing, so callers
must treat it as a planning hint rather than a simulation result.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from grid_td.enemies import Enemy, create_enemy
from grid_td.position import LEGACY_TILE_SIZE, Position, WorldPosition
from grid_td.waves import THREAT_LEVELS, Wave


@dataclass(frozen=True)
class WaveSpawnIntel:
    """One scheduled enemy spawn in detailed intel."""

    at_seconds: float  # Logical seconds after the wave starts.
    enemy_kind: str  # Template key used by create_enemy().
    enemy_name: str  # Player-facing enemy name.
    entrance_index: int  # Zero-based spawn entrance assigned by the group.


@dataclass(frozen=True)
class WaveGroupIntel:
    """Detailed aggregate for one spawn group."""

    enemy_kind: str
    enemy_name: str
    count: int
    entrance_index: int
    entrance: Position | None  # None when a manually built wave is invalid.
    start_delay_seconds: float
    interval_seconds: float
    first_spawn_seconds: float
    last_spawn_seconds: float
    tags: tuple[str, ...]  # Enemy traits such as "fast" or "grid_saboteur".


@dataclass(frozen=True)
class WaveIntel:
    """Read-only intel for one wave, at either preview or detailed level.

    Preview intel leaves the detailed-only fields empty/None. Detailed intel
    fills every field. Presentation code can rely on ``is_detailed`` instead of
    probing individual fields.
    """

    wave_index: int
    wave_name: str
    briefing: str
    is_detailed: bool
    enemy_kinds: tuple[str, ...]
    enemy_names: tuple[str, ...]
    tags: tuple[str, ...]
    threat: str  # One of THREAT_LEVELS.
    entrances: tuple[Position, ...]  # Unique spawn points used by this wave.
    total_enemies: int | None = None
    spawn_window_seconds: float | None = None
    estimated_duration_seconds: float | None = None
    groups: tuple[WaveGroupIntel, ...] = ()
    spawn_timeline: tuple[WaveSpawnIntel, ...] = ()
    primary_route: tuple[WorldPosition, ...] = ()


def enemy_tags(enemy: Enemy) -> tuple[str, ...]:
    """Derive stable trait tags from an enemy template.

    The thresholds follow the current templates: fast enemies are at least one
    legacy tile per second, armored enemies have positive flat armor, and
    saboteurs target power buildings. Keep this function as the single place
    that maps combat stats to player-facing intel tags.
    """
    tags: list[str] = []
    if enemy.armor > 0:
        tags.append("armored")
    if enemy.targets_power_buildings:
        tags.append("grid_saboteur")
    if enemy.speed >= LEGACY_TILE_SIZE:
        tags.append("fast")
    return tuple(tags)


def _derive_threat(
    total_enemies: int, armored_count: int, saboteur_count: int
) -> str:
    """Classify a wave with a deterministic, author-overridable heuristic.

    Armored and saboteur units contribute more than raw count because they put
    pressure on specific defenses. The thresholds are intentionally simple so
    tests and designers can predict them; TOML ``threat`` overrides this value.
    """
    score = total_enemies + 2 * armored_count + 3 * saboteur_count
    if score <= 6:
        return "low"
    if score <= 12:
        return "medium"
    return "high"


def _unique_append(values: list[str], value: str) -> None:
    """Append in first-seen order so intel is stable across runs."""
    if value not in values:
        values.append(value)


def build_wave_intel(
    wave: Wave,
    wave_index: int,
    entrances: tuple[Position, ...],
    primary_route: tuple[WorldPosition, ...],
    route_length: float,
) -> WaveIntel:
    """Build the full detailed intel object for one wave.

    Args:
        wave: Static wave configuration.
        wave_index: Zero-based position in the level's wave tuple.
        entrances: Map spawn points indexed by ``SpawnGroup.entrance``.
        primary_route: Primary centerline points for route preview.
        route_length: Primary route length used for the duration estimate.

    Returns:
        A frozen detailed ``WaveIntel``. Use ``preview_wave_intel()`` to hide
        detailed-only fields for the free tier.
    """
    enemy_kinds: list[str] = []
    enemy_names: list[str] = []
    all_tags: list[str] = []
    unique_entrances: list[Position] = []
    groups: list[WaveGroupIntel] = []
    timeline: list[tuple[float, int, WaveSpawnIntel]] = []
    total_enemies = 0
    armored_count = 0
    saboteur_count = 0
    first_spawns: list[float] = []
    last_spawns: list[float] = []
    estimated_durations: list[float] = []

    for group_index, group in enumerate(wave.groups):
        template = create_enemy(group.enemy_kind)
        tags = enemy_tags(template)
        entrance = (
            entrances[group.entrance]
            if 0 <= group.entrance < len(entrances)
            else None
        )
        if entrance is not None:
            _unique_append(unique_entrances, entrance)

        _unique_append(enemy_kinds, group.enemy_kind)
        _unique_append(enemy_names, template.name)
        for tag in tags:
            _unique_append(all_tags, tag)

        first_spawn = group.start_delay_seconds
        last_spawn = group.start_delay_seconds + (
            group.count - 1
        ) * group.interval_seconds
        first_spawns.append(first_spawn)
        last_spawns.append(last_spawn)
        total_enemies += group.count
        if template.armor > 0:
            armored_count += group.count
        if template.targets_power_buildings:
            saboteur_count += group.count
        estimated_durations.append(last_spawn + route_length / template.speed)

        groups.append(
            WaveGroupIntel(
                enemy_kind=group.enemy_kind,
                enemy_name=template.name,
                count=group.count,
                entrance_index=group.entrance,
                entrance=entrance,
                start_delay_seconds=group.start_delay_seconds,
                interval_seconds=group.interval_seconds,
                first_spawn_seconds=first_spawn,
                last_spawn_seconds=last_spawn,
                tags=tags,
            )
        )

        for spawned in range(group.count):
            at_seconds = group.start_delay_seconds + spawned * group.interval_seconds
            timeline.append(
                (
                    at_seconds,
                    group_index,
                    WaveSpawnIntel(
                        at_seconds=at_seconds,
                        enemy_kind=group.enemy_kind,
                        enemy_name=template.name,
                        entrance_index=group.entrance,
                    ),
                )
            )

    if len(enemy_kinds) > 1:
        _unique_append(all_tags, "mixed")

    # Stable tie-break by group index keeps same-time spawns deterministic.
    timeline.sort(key=lambda item: (item[0], item[1]))
    threat = wave.threat or _derive_threat(
        total_enemies, armored_count, saboteur_count
    )

    return WaveIntel(
        wave_index=wave_index,
        wave_name=wave.name,
        briefing=wave.briefing,
        is_detailed=True,
        enemy_kinds=tuple(enemy_kinds),
        enemy_names=tuple(enemy_names),
        tags=tuple(all_tags),
        threat=threat,
        entrances=tuple(unique_entrances),
        total_enemies=total_enemies,
        spawn_window_seconds=max(last_spawns) - min(first_spawns),
        estimated_duration_seconds=max(estimated_durations),
        groups=tuple(groups),
        spawn_timeline=tuple(item[2] for item in timeline),
        primary_route=primary_route,
    )


def preview_wave_intel(intel: WaveIntel) -> WaveIntel:
    """Return the free preview projection of detailed wave intel.

    The projection keeps only coarse fields, so free intel cannot accidentally
    leak exact counts, spawn timing, group entrances, or route geometry.
    """
    return replace(
        intel,
        is_detailed=False,
        total_enemies=None,
        spawn_window_seconds=None,
        estimated_duration_seconds=None,
        groups=(),
        spawn_timeline=(),
        primary_route=(),
    )
