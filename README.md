# Critical Grid

Critical Grid is a minimalist grid-based tower defense prototype built in Python.

The current goal is not to build a full commercial game. Instead, this project starts with a clear, runnable, object-oriented core so the game rules can be learned, tested, and expanded step by step.

## Developer Orientation

The runtime has one authoritative state object: `GameState`. The normal data
flow is:

```text
main.py
  -> GameState
     -> GridMap / Position       map and coordinate rules
     -> Building / Enemy         mutable domain entities
     -> PowerGrid                 connection and efficiency calculation
     -> WaveRunner                enemy spawn schedule
     -> snapshot()                read-only presentation contract
  -> TextRenderer                 text projection of the snapshot contract
```

`GameState.step(seconds)` is the simulation boundary. Each NIGHT step spawns due
enemies, recalculates power, lets connected towers attack, then advances
enemies toward the core. Wave settlement is separate: `end_wave()` applies
mine income, debt interest, and repair costs, while `start_next_wave()` creates
the next spawn runner.

Presentation layers should read through `GameState.snapshot()` rather than
accessing mutable state lists and counters directly. The snapshot contains a
status object plus a row-major board of cell snapshots, so both text and GUI
frontends can render the same source of truth.

The current Python prototype is intentionally smaller than
`GAME_DESIGN.md`: the power grid propagates through the core, power plants and
power nodes using a six-world-unit coverage radius; ordinary buildings do not
relay power. The demo contains four waves, routing is fixed, and building
health/damage is not yet modeled as mutable state. Treat the code as the
behavioral source of truth when changing the prototype; use the design document
for planned features and unresolved rules.

Recommended reading order:

1. `main.py` for the runnable scenario.
2. `grid_td/game_state.py` for orchestration and state transitions.
3. `GameState.snapshot()` and its snapshot dataclasses for the GUI/text read
   contract.
4. `grid_td/buildings.py`, `grid_td/enemies.py`, and `grid_td/waves.py` for
   domain behavior.
5. `grid_td/power_grid.py` for connectivity and efficiency side effects.
6. `grid_td/map.py`, `grid_td/position.py`, and `grid_td/renderer.py` for
   supporting rules and output.
7. `tests/test_core_loop.py` for the currently protected behavior.

## Wave Lifecycle

New games start in `GamePhase.DAY` with no wave runner. The player can build
and buy intel while all simulation clocks remain frozen. The lifecycle is
`DAY -> NIGHT -> DAY`, followed by `VICTORY` after the final settlement or
`DEFEAT` when core health reaches zero. Pause remains a frontend time control,
not a replacement phase.

```python
from grid_td.game_state import GamePhase, GameState
from grid_td.map import create_demo_map

game = GameState(create_demo_map())  # Planning day; no enemies spawn.
# On the player's Start Night action (including the first night):
game.start_next_wave()
```

During combat, use the snapshot to check whether the night can be settled:

```python
if game.snapshot().status.waiting_for_next_wave:
    message = game.end_wave()
    # Return to planning. Wait for another Start Night action.
```

- `snapshot().status.phase` exposes `GamePhase.DAY`, `NIGHT`, `VICTORY`, or
  `DEFEAT`; their string values are `day`, `night`, `victory`, and `defeat`.
  `GameStatus` constructors now require this field. During DAY, `wave_index`
  and `current_wave_name` describe the upcoming night; NIGHT uses the same index.
- `waiting_for_next_wave` is true only during NIGHT while the game is
  unfinished, the core is alive, spawning is complete, and no enemies remain.
- `end_wave()` returns a settlement string. It pays mine income, charges
  interest and repairs, clears repair markers, advances the wave index, and
  removes the runner exactly once. Settlement enters DAY, except that the final
  wave records VICTORY directly without another planning day.
- `start_next_wave()` returns `None` and creates a runner only during DAY,
  including the first day. It enters NIGHT without advancing the wave index
  or clocks. It cannot restart an active or cleared-but-unsettled wave.
- Both commands raise `ValueError` for invalid transitions, including calls
  after victory or defeat, and leave state unchanged on rejection. Defeat is
  recorded by `step()` and is not followed by wave settlement.

GUI migration is required: initialize in DAY, offer a Start Night action,
and remove immediate next-wave startup after settlement. Keep Run/Pause
separate from starting a night. The existing `gui/` is not yet migrated and
will remain in DAY until it calls `start_next_wave()`; its previous automatic
startup after settlement would skip planning. This change only updates the
core and text demo. Frontends should catch `ValueError` for rejected commands.

Build and intel commands also reject a destroyed core or ended game without
changing state. `buy_wave_intel()` checks wave availability before charging:
when no waves remain in a non-terminal state it returns `"No incoming wave."`
for free.

## World Geometry and Placement

One small cell is **one world unit** on each axis. Each former demo tile is
subdivided into 3 by 3 small cells: the map is now **36 by 21**, with the
same physical layout. Coordinates use the top-left origin, with x pointing
right and y pointing down. `Position` accepts integer small-cell coordinates;
`WorldPosition` accepts finite continuous coordinates. A cell `(x, y)` covers
`[x, x + 1)` by `[y, y + 1)`, with center `(x + 0.5, y + 0.5)`.

- `Building.position` is the top-left occupied cell. All current building
  types occupy 3 by 3 cells, including the core. Anchors may move by one small
  cell; they do not have to align to multiples of three.
- Each concrete type declares an immutable `FOOTPRINT = Footprint(width,
  height)` in `buildings.py`. New instances capture that size; changing a
  type's configuration does not resize existing entities. Rectangular and
  even-sized footprints are supported. A custom map's `core_footprint` defines
  both the reserved core terrain and the runtime core's size.
- The whole footprint must fit inside the map and avoid roads, blocked cells,
  the core, and other buildings. Mines must fit entirely inside mine terrain;
  other buildings cannot overlap it. High-ground range bonuses require full
  footprint coverage.
- Power conducts between four-neighbor occupied cells along building edges.
  Partial edge contact connects; diagonal-only contact and empty gaps do not.
  Supply, demand and connected counts include each building once, regardless
  of its size.
- Base tower range is 6 units, or 9 on high ground. Basic enemy speed is 2.25
  units per logical second; other template speeds also scale by three. Spawn
  times, cooldowns, overload durations, costs and wave settlement do not scale.

`GameState.preview_build(kind, position)` returns an immutable `BuildPreview`
with `position`, `width`, `height`, `occupied_cells`, `is_valid` and `reason`.
It checks the same rules as `build()`, including gold and terminal state,
without changing gold, IDs, occupancy or power. Unknown kinds and malformed
arguments raise `ValueError`; ordinary placement failures return an invalid
preview with a reason. A valid preview has an empty reason. `build()` always
rechecks current rules and raises `ValueError` on rejection, without mutation.

```python
from grid_td.position import Position

# Former anchor (10, 2) becomes (30, 6), occupying x=30..32 and y=6..8.
preview = game.preview_build("gun_tower", Position(30, 6))
if preview.is_valid:
    game.build("gun_tower", preview.position)
```

`building_at(position)` and `cell_snapshot(position)` resolve any covered cell
to the same building ID and anchor. `CellSnapshot.is_buildable` remains a
single-cell hint: use `preview_build()` to validate an entire building.
Removing a tower releases all its occupied cells.

Road terrain and movement geometry are separate. `GridMap.road_cells` stores
the full road surface, while `route` stores orthogonal centerline waypoints in
small-cell coordinates. If road terrain is omitted, it defaults to a one-cell
wide line between waypoints. `GridMap.path` is an immutable `RoutePath` with
world-space points at waypoint cell centers. The demo path length is 36 units,
preserving the original travel time after scaling enemy speeds by three.
Progress and arrival use physical path distance, independent of waypoint
spacing; arrival remains at the final core-adjacent centerline point.

Combat uses the building center and the enemy's continuous world position.
The `world_distance()` function in `position.py` is the shared combat-distance
interface and currently uses Manhattan distance, including the exact range
boundary. A future metric change belongs there; power adjacency and physical
path lengths are independent. Continuous targeting changes attack timing from
the previous discrete-cell checks, so identical final combat results are not
guaranteed. Dead enemies cannot absorb another tower's attack before cleanup.

### Snapshot and GUI Migration

The core and text demo are migrated; **GUI code is unchanged and requires
adaptation** before use with this spatial contract:

- `GameSnapshot` adds required fields `cell_size` (currently `1.0` world unit)
  and `distance_metric` (`"manhattan"`). Map width/height are small-cell counts.
- `BuildingSnapshot` adds required `width`, `height` and `center`. Draw/select
  the full footprint using its anchor, and deduplicate by ID when collecting
  buildings from board cells. Every covered cell exposes that building.
- `EnemySnapshot` adds required `world_position`. Use it for continuous drawing;
  `position` is the containing small cell. `speed` is in world units per second,
  and `path_progress` is world distance, **not a route-list index**. Do not use
  `route[int(path_progress)]` or reconstruct positions from waypoint indices.
- Entity-level `position_on_route()` and `has_reached_core()` now take a
  `RoutePath` (`grid_map.path`), rather than a waypoint tuple. Presentation
  code should read snapshots instead of calling these domain methods.
- Convert mouse coordinates to small-cell anchors and preview full footprints
  through `preview_build()`. Pixel size per small cell is a GUI decision; the
  core does not depend on rendering scale. Use core geometry for targeting and
  range feedback instead of repeating the old discrete-cell range rules.
- Tools/tests that manually construct snapshot dataclasses must provide the
  new required fields. Existing coordinates migrate by multiplying anchors by
  three; existing distance/speed values also multiply by three. Do not migrate
  seconds, damage, gold or power values.

## Simulation Clock

`GameState` owns the authoritative logical clock. Each call to
`game.step(seconds)` during NIGHT advances that same finite, non-negative delta
through the wave scheduler, tower cooldowns, overload timers, enemy movement, and
`elapsed_seconds`. A fixed-step caller can use `0.05` seconds for 20 logical
updates per second; the core does not start its own timer or event loop.
DAY freezes elapsed time, spawning, cooldowns, overload timers, and movement;
valid steps do nothing. `elapsed_seconds` accumulates combat time across all
nights, while each new wave runner starts its local spawn clock at zero.

`elapsed_seconds` is a float so fractional steps accumulate without integer
rounding. During NIGHT, `step(0)` remains valid and processes events scheduled at
logical time zero. Invalid durations are rejected in every phase, including
DAY and terminal phases. Negative, non-finite, boolean, string, and
unrepresentably large values raise `ValueError` without changing state.

## Emergency Commands

- `core_overdraft(gold_amount=40)` accepts a positive integer, excluding
  booleans and floats. It adds the amount to gold and `round(amount * 1.35)`
  to debt. Amounts that overflow the debt calculation are rejected.
- `overload_tower(building_id, seconds=8.0)` requires a positive integer ID
  belonging to an existing tower and a finite positive `int` or `float`
  duration representable as a float. Booleans are rejected for both arguments.
  Each successful call adds 10 debt and marks the tower for repair; repeated
  calls keep the longer remaining overload duration.
- Both commands return `None`. They raise `ValueError` for invalid arguments,
  a destroyed core, or an ended game, without changing gold, debt, repair
  markers, or overload timers. Frontends should catch and display this error.

Default arguments and valid calls keep their existing behavior. The GUI's
selected-tower call `game.overload_tower(tower.id)` remains supported.

## Project Structure

```text
.
├── GAME_DESIGN.md          # Core gameplay design document
├── README.md               # Project structure and usage guide
├── main.py                 # Runs a minimal text-based demo
├── grid_td/
│   ├── __init__.py         # Package entry
│   ├── position.py         # Cells, world positions, footprints and distance policy
│   ├── path.py             # Distance-based fixed-route sampling
│   ├── map.py              # Grid map, route, mine sites, buildable areas
│   ├── buildings.py        # Buildings and tower classes
│   ├── enemies.py          # Enemy classes and enemy templates
│   ├── power_grid.py       # Power-grid connection and efficiency calculation
│   ├── waves.py            # Wave and spawn logic
│   ├── game_state.py       # Game state and core rules
│   └── renderer.py         # Text renderer
└── tests/
    └── test_core_loop.py   # Core logic tests
```

## Run

```bash
python3 main.py
```

## Test

```bash
python3 -m unittest discover -s tests
```

## Current Features

- 36 by 21 small-cell map with configurable rectangular building footprints.
- Enemy movement along a fixed route.
- Buildable mines, power plants, power nodes, and three tower types.
- Power-grid connection calculation.
- Reduced building efficiency when power is insufficient.
- Wave spawning.
- Core overdraft.
- Tower overload.
- Text-based map rendering.

## Next Steps

This is currently a pure logic prototype. Future work can move in two directions:

- Improve the Python logic: balance numbers, add enemies, towers, intel, and technology.
- Add a graphical interface, such as Pygame, while keeping the existing object system.

