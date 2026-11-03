"""TOML-backed level definitions.

A level bundles the fixed map, enemy wave schedule, and starting resources.
Enemy spawn points are declared per map and selected by each spawn group. The
TOML file is the single source of truth for playable levels; the legacy
``create_demo_map()`` and ``create_demo_waves()`` helpers load this module's
demo file so existing callers keep working.

The loader validates the entire document before constructing runtime objects.
Unknown fields and overlapping terrain are rejected so data mistakes fail at
startup instead of producing a subtly broken map. Positions and rectangles use
small-cell coordinates; a rectangle is ``[x, y, width, height]``.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from grid_td.enemies import create_enemy
from grid_td.map import GridMap
from grid_td.pathing import find_path
from grid_td.position import Footprint, Position
from grid_td.waves import SpawnGroup, Wave

LEVELS_DIRECTORY = Path(__file__).resolve().parent.parent / "levels"
DEMO_LEVEL_PATH = LEVELS_DIRECTORY / "demo.toml"

_LEVEL_KEYS = frozenset(
    {"name", "description", "starting_gold", "starting_core_hp", "map", "waves"}
)
_MAP_KEYS = frozenset(
    {
        "width",
        "height",
        "route",
        "entrances",
        "core_position",
        "core_footprint",
        "terrain",
    }
)
_TERRAIN_KEYS = (
    "road",
    "mine",
    "high_ground",
    "illegal",
    "walk_only",
    "build_only",
)
_WAVE_KEYS = frozenset({"name", "briefing", "groups"})
_GROUP_KEYS = frozenset(
    {"enemy_kind", "count", "interval_seconds", "start_delay_seconds", "entrance"}
)


@dataclass(frozen=True)
class LevelDefinition:
    """A complete playable level loaded from TOML."""

    name: str
    description: str
    grid_map: GridMap
    waves: tuple[Wave, ...]
    starting_gold: int
    starting_core_hp: int

    def __post_init__(self) -> None:
        """Reject manually constructed levels that bypass loader validation."""
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Level name must be a nonempty string.")
        if not isinstance(self.description, str):
            raise ValueError("Level description must be a string.")
        if not isinstance(self.grid_map, GridMap):
            raise ValueError("Level grid_map must be a GridMap.")
        if not isinstance(self.waves, tuple) or not self.waves:
            raise ValueError("Level waves must be a nonempty tuple.")
        if any(not isinstance(wave, Wave) for wave in self.waves):
            raise ValueError("Level waves must contain Wave values.")
        if (
            isinstance(self.starting_gold, bool)
            or not isinstance(self.starting_gold, int)
            or self.starting_gold < 0
        ):
            raise ValueError("Level starting_gold must be a non-negative integer.")
        if (
            isinstance(self.starting_core_hp, bool)
            or not isinstance(self.starting_core_hp, int)
            or self.starting_core_hp <= 0
        ):
            raise ValueError("Level starting_core_hp must be a positive integer.")


def load_level(path: str | Path) -> LevelDefinition:
    """Load and validate one level TOML file.

    Args:
        path: Path to a level document.

    Returns:
        A frozen level definition containing the map, waves, and starting
        resources.

    Raises:
        FileNotFoundError: The path does not exist.
        ValueError: The file is not valid TOML or violates the level schema.
    """
    level_path = Path(path)
    try:
        with level_path.open("rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{level_path}: invalid TOML: {exc}") from exc
    return _parse_level(data, level_path)


def load_demo_level() -> LevelDefinition:
    """Load the bundled demo level used by the entry script and tests."""
    return load_level(DEMO_LEVEL_PATH)


def _error(path: Path, context: str, message: str) -> ValueError:
    return ValueError(f"{path}: {context}: {message}")


def _require_mapping(value: object, context: str, path: Path) -> dict:
    if not isinstance(value, dict):
        raise _error(path, context, "must be a TOML table.")
    return value


def _check_keys(data: dict, allowed: frozenset[str], context: str, path: Path) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise _error(path, context, f"unknown field(s): {', '.join(unknown)}.")


def _require_int(
    value: object, context: str, path: Path, *, minimum: int | None = None
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(path, context, "must be an integer.")
    if minimum is not None and value < minimum:
        raise _error(path, context, f"must be at least {minimum}.")
    return value


def _require_number(
    value: object,
    context: str,
    path: Path,
    *,
    minimum: float | None = None,
    positive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(path, context, "must be a number.")
    try:
        number = float(value)
    except OverflowError:
        raise _error(path, context, "must be a finite number.") from None
    if not isfinite(number):
        raise _error(path, context, "must be a finite number.")
    if positive and number <= 0:
        raise _error(path, context, "must be greater than zero.")
    if minimum is not None and number < minimum:
        raise _error(path, context, f"must be at least {minimum}.")
    return number


def _require_string(
    value: object, context: str, path: Path, *, nonempty: bool = False
) -> str:
    if not isinstance(value, str):
        raise _error(path, context, "must be a string.")
    if nonempty and not value.strip():
        raise _error(path, context, "must not be empty.")
    return value


def _parse_position(value: object, context: str, path: Path) -> Position:
    if not isinstance(value, list) or len(value) != 2:
        raise _error(path, context, "must be an [x, y] array.")
    return Position(
        _require_int(value[0], f"{context}[0]", path),
        _require_int(value[1], f"{context}[1]", path),
    )


def _parse_rectangle(
    value: object, context: str, path: Path, width: int, height: int
) -> tuple[int, int, int, int]:
    if not isinstance(value, list) or len(value) != 4:
        raise _error(path, context, "must be an [x, y, width, height] array.")
    x = _require_int(value[0], f"{context}[0]", path, minimum=0)
    y = _require_int(value[1], f"{context}[1]", path, minimum=0)
    rect_width = _require_int(value[2], f"{context}[2]", path, minimum=1)
    rect_height = _require_int(value[3], f"{context}[3]", path, minimum=1)
    if x + rect_width > width or y + rect_height > height:
        raise _error(path, context, "extends outside the map.")
    return x, y, rect_width, rect_height


def _rectangle_cells(rectangle: tuple[int, int, int, int]) -> set[Position]:
    x, y, width, height = rectangle
    return {
        Position(cell_x, cell_y)
        for cell_y in range(y, y + height)
        for cell_x in range(x, x + width)
    }


def _parse_terrain(
    value: object,
    context: str,
    path: Path,
    width: int,
    height: int,
    core_cells: frozenset[Position],
) -> dict[str, frozenset[Position] | None]:
    terrain = _require_mapping(value, context, path)
    _check_keys(terrain, frozenset(_TERRAIN_KEYS), context, path)

    sets: dict[str, frozenset[Position] | None] = {}
    for name in _TERRAIN_KEYS:
        if name not in terrain:
            sets[name] = None if name == "road" else frozenset()
            continue
        rectangles = terrain[name]
        if not isinstance(rectangles, list):
            raise _error(path, f"{context}.{name}", "must be an array of rectangles.")
        cells: set[Position] = set()
        for index, rectangle in enumerate(rectangles):
            cells.update(
                _rectangle_cells(
                    _parse_rectangle(
                        rectangle,
                        f"{context}.{name}[{index}]",
                        path,
                        width,
                        height,
                    )
                )
            )
        sets[name] = frozenset(cells)

    populated = [(name, cells) for name, cells in sets.items() if cells]
    for index, (first_name, first_cells) in enumerate(populated):
        overlap = first_cells & core_cells
        if overlap:
            cell = min(overlap)
            raise _error(
                path,
                f"{context}.{first_name}",
                f"overlaps the core footprint at ({cell.x}, {cell.y}).",
            )
        for second_name, second_cells in populated[index + 1 :]:
            overlap = first_cells & second_cells
            if overlap:
                cell = min(overlap)
                raise _error(
                    path,
                    f"{context}.{first_name}",
                    f"overlaps {second_name} at ({cell.x}, {cell.y}).",
                )

    return sets


def _parse_map(value: object, path: Path) -> GridMap:
    map_data = _require_mapping(value, "map", path)
    _check_keys(map_data, _MAP_KEYS, "map", path)

    width = _require_int(map_data.get("width"), "map.width", path, minimum=1)
    height = _require_int(map_data.get("height"), "map.height", path, minimum=1)

    if "route" not in map_data:
        raise _error(path, "map.route", "is required.")
    route_value = map_data["route"]
    if not isinstance(route_value, list) or not route_value:
        raise _error(path, "map.route", "must be a nonempty array of [x, y] points.")
    route = tuple(
        _parse_position(point, f"map.route[{index}]", path)
        for index, point in enumerate(route_value)
    )

    entrances: tuple[Position, ...] = ()
    if "entrances" in map_data:
        entrance_value = map_data["entrances"]
        if not isinstance(entrance_value, list) or not entrance_value:
            raise _error(
                path,
                "map.entrances",
                "must be a nonempty array of [x, y] points.",
            )
        entrances = tuple(
            _parse_position(point, f"map.entrances[{index}]", path)
            for index, point in enumerate(entrance_value)
        )

    if "core_position" not in map_data:
        raise _error(path, "map.core_position", "is required.")
    core_position = _parse_position(map_data["core_position"], "map.core_position", path)
    footprint_value = map_data.get("core_footprint", [3, 3])
    if not isinstance(footprint_value, list) or len(footprint_value) != 2:
        raise _error(path, "map.core_footprint", "must be a [width, height] array.")
    core_footprint = Footprint(
        _require_int(footprint_value[0], "map.core_footprint[0]", path, minimum=1),
        _require_int(footprint_value[1], "map.core_footprint[1]", path, minimum=1),
    )
    core_cells = frozenset(core_footprint.cells(core_position))

    terrain = _parse_terrain(
        map_data.get("terrain", {}),
        "map.terrain",
        path,
        width,
        height,
        core_cells,
    )

    try:
        grid_map = GridMap(
            width=width,
            height=height,
            route=route,
            core_position=core_position,
            mine_positions=terrain["mine"],
            high_ground_positions=terrain["high_ground"],
            illegal_ground_positions=terrain["illegal"],
            road_cells=terrain["road"],
            core_footprint=core_footprint,
            walk_only_positions=terrain["walk_only"],
            build_only_positions=terrain["build_only"],
            entrances=entrances,
        )
    except ValueError as exc:
        raise _error(path, "map", str(exc)) from exc

    for cell in grid_map.centerline_cells:
        if not grid_map.is_walkable(cell):
            raise _error(
                path,
                "map.route",
                f"centerline cell ({cell.x}, {cell.y}) is not walkable.",
            )

    for index, entrance in enumerate(grid_map.spawn_entrances):
        context = (
            f"map.entrances[{index}]" if entrances else "map.route[0]"
        )
        try:
            plan = find_path(
                grid_map,
                [],
                entrance,
                enemy_speed=1.0,
                breach_damage=1.0,
            )
        except ValueError as exc:
            raise _error(path, context, str(exc)) from exc
        if plan is None:
            raise _error(path, context, "cannot reach the core.")
    return grid_map


def _parse_waves(
    value: object, path: Path, entrance_count: int
) -> tuple[Wave, ...]:
    if not isinstance(value, list) or not value:
        raise _error(path, "waves", "must be a nonempty array of wave tables.")

    waves: list[Wave] = []
    names: set[str] = set()
    for wave_index, wave_value in enumerate(value):
        context = f"waves[{wave_index}]"
        wave_data = _require_mapping(wave_value, context, path)
        _check_keys(wave_data, _WAVE_KEYS, context, path)

        name = _require_string(
            wave_data.get("name"), f"{context}.name", path, nonempty=True
        )
        if name in names:
            raise _error(path, f"{context}.name", f"duplicate wave name: {name}.")
        names.add(name)
        briefing = _require_string(
            wave_data.get("briefing", ""), f"{context}.briefing", path
        )

        groups_value = wave_data.get("groups")
        if not isinstance(groups_value, list) or not groups_value:
            raise _error(path, f"{context}.groups", "must be a nonempty array.")
        groups: list[SpawnGroup] = []
        for group_index, group_value in enumerate(groups_value):
            group_context = f"{context}.groups[{group_index}]"
            group_data = _require_mapping(group_value, group_context, path)
            _check_keys(group_data, _GROUP_KEYS, group_context, path)

            enemy_kind = _require_string(
                group_data.get("enemy_kind"),
                f"{group_context}.enemy_kind",
                path,
                nonempty=True,
            )
            try:
                create_enemy(enemy_kind)
            except ValueError as exc:
                raise _error(
                    path, f"{group_context}.enemy_kind", str(exc)
                ) from exc

            entrance = _require_int(
                group_data.get("entrance", 0),
                f"{group_context}.entrance",
                path,
                minimum=0,
            )
            if entrance >= entrance_count:
                raise _error(
                    path,
                    f"{group_context}.entrance",
                    f"must be less than the entrance count ({entrance_count}).",
                )

            groups.append(
                SpawnGroup(
                    enemy_kind=enemy_kind,
                    count=_require_int(
                        group_data.get("count"), f"{group_context}.count", path, minimum=1
                    ),
                    interval_seconds=_require_number(
                        group_data.get("interval_seconds"),
                        f"{group_context}.interval_seconds",
                        path,
                        positive=True,
                    ),
                    start_delay_seconds=_require_number(
                        group_data.get("start_delay_seconds", 0.0),
                        f"{group_context}.start_delay_seconds",
                        path,
                        minimum=0.0,
                    ),
                    entrance=entrance,
                )
            )
        waves.append(Wave(name=name, briefing=briefing, groups=tuple(groups)))
    return tuple(waves)


def _parse_level(data: object, path: Path) -> LevelDefinition:
    level_data = _require_mapping(data, "level", path)
    _check_keys(level_data, _LEVEL_KEYS, "level", path)

    name = _require_string(level_data.get("name"), "name", path, nonempty=True)
    description = _require_string(level_data.get("description", ""), "description", path)
    starting_gold = _require_int(
        level_data.get("starting_gold"), "starting_gold", path, minimum=0
    )
    starting_core_hp = _require_int(
        level_data.get("starting_core_hp"), "starting_core_hp", path, minimum=1
    )
    if "map" not in level_data:
        raise _error(path, "map", "is required.")
    grid_map = _parse_map(level_data["map"], path)
    if "waves" not in level_data:
        raise _error(path, "waves", "is required.")
    waves = _parse_waves(
        level_data["waves"],
        path,
        len(grid_map.spawn_entrances),
    )
    return LevelDefinition(
        name=name,
        description=description,
        grid_map=grid_map,
        waves=waves,
        starting_gold=starting_gold,
        starting_core_hp=starting_core_hp,
    )
