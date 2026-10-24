# Critical Grid

Critical Grid is a minimalist grid-based tower defense prototype built in Python.

The current goal is not to build a full commercial game. Instead, this project starts with a clear, runnable, object-oriented core so the game rules can be learned, tested, and expanded step by step.

## Developer Orientation

The runtime has one authoritative state object: `GameState`. The normal data
flow is:

```text
main.py / gui/gui.py
  -> GameState
     -> GridMap / Position       map and coordinate rules
     -> Building / Enemy         mutable domain entities
     -> PowerGrid                 connection and efficiency calculation
     -> WaveRunner                enemy spawn schedule
     -> snapshot()                read-only presentation contract
  -> TextRenderer / GUI          presentation consumers
```

`GameState.step(seconds)` is the simulation boundary. Each NIGHT step spawns due
enemies, recalculates power, lets connected towers attack, advances enemies,
then lets saboteurs attack power nodes. Wave settlement is separate:
`end_wave()` applies
mine income, debt interest, and repair costs, while `start_next_wave()` creates
the next spawn runner.

Presentation layers should read through `GameState.snapshot()` rather than
accessing mutable state lists and counters directly. The snapshot contains a
status object plus a row-major board of cell snapshots, so both text and GUI
frontends can render the same source of truth.

The current Python prototype is intentionally smaller than
`GAME_DESIGN.md`: the power grid propagates through the core, power plants and
power nodes using a six-world-unit coverage radius; ordinary buildings do not
relay power. Every building has mutable health, condition-based efficiency,
and gold-funded repair; saboteurs currently attack only power nodes. Other
enemy building targets and dynamic routing are still pending. Treat the code as the
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
7. `gui/gui.py` for the Pygame frontend and its use of public commands.
8. `tests/` for the currently protected behavior, with `test_core_loop.py` as
   the main end-to-end entry point.

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

The core, text demo, and `gui/` frontend follow this lifecycle. The GUI
initializes in DAY, exposes a separate Start Night action, and returns to
planning after each settled night. Run/Pause only controls simulation time and
does not start a night. Frontends should catch `ValueError` for rejected
commands.

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
- Power propagates from the core, power plants, and power nodes to every
  building whose center is within an inclusive six-world-unit Manhattan radius
  of a connected transmitter. Ordinary buildings cannot relay power, so a
  powered mine or tower never extends coverage to another building. Supply,
  demand and connected counts include each building once, regardless of its
  size.
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

### Snapshot and GUI Contract

The core, text demo, and `gui/` presentation layer all use the snapshot
contract:

- `GameSnapshot` provides required fields `cell_size` (currently `1.0` world
  unit) and `distance_metric` (`"manhattan"`). Map width/height are small-cell
  counts.
- `BuildingSnapshot` provides required `width`, `height` and `center`. Draw and
  select the full footprint using its anchor, and deduplicate by ID when
  collecting buildings from board cells. Every covered cell exposes that
  building.
- `EnemySnapshot` provides required `world_position`. Use it for continuous
  drawing; `position` is the containing small cell. `speed` is in world units
  per second, and `path_progress` is world distance, **not a route-list index**.
  Do not use `route[int(path_progress)]` or reconstruct positions from waypoint
  indices.
- Entity-level `position_on_route()` and `has_reached_core()` take a `RoutePath`
  (`grid_map.path`), rather than a waypoint tuple. Presentation code should read
  snapshots instead of calling these domain methods.
- Convert mouse coordinates to small-cell anchors and preview full footprints
  through `preview_build()`. Pixel size per small cell is a GUI decision; the
  core does not depend on rendering scale. Use core geometry for targeting and
  range feedback instead of repeating the old discrete-cell range rules.
- Tools/tests that manually construct snapshot dataclasses must provide the
  required fields. Existing coordinates migrate by multiplying anchors by
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

## Building Health and Repair

Every building, including the core, stores `max_hp` and `current_hp` and exposes
`hp`, `is_destroyed`, `take_damage(amount)`, `repair_cost`, and `repair()`.
`take_damage()` accepts positive integers (excluding booleans) and clamps HP
at zero. The entity-level `repair()` restores full health and returns the HP
restored; it does not charge gold. Presentation code must use the game command
below rather than calling entity methods or assigning health directly.

```python
building = game.cell_snapshot(selected_position).building
if building is not None:
    # Show building.hp, building.max_hp and building.repair_cost in the GUI.
    try:
        gold_spent = game.repair_building(building.id)
    except ValueError as error:
        print(error)
```

- `repair_building(building_id) -> int` repairs the entire building instantly
  and returns the gold spent. Each missing HP costs **1 gold**; partial repairs
  and repair timers are not implemented. DAY and NIGHT both allow repairs.
- The ID must be a positive integer, excluding booleans. Missing/demolished
  buildings, full-health buildings, insufficient gold, a destroyed core, and
  ended games raise `ValueError` without changing state. There is no partial
  payment or repair when gold is insufficient.
- Zero-HP non-core buildings remain on the map and can be repaired through the
  same command, preserving their IDs and footprints. Successful repairs
  immediately recalculate power: restoring a node can reconnect downstream
  buildings, and restoring a plant can restore its supply.
- Health condition uses ten-percent bands. `90%~100% HP` has condition
  efficiency `100%`; below 90%, each lower band reduces it by 10 percentage
  points (`80%~<90%` gives `90%`, `70%~<80%` gives `80%`, and so on); `0 HP`
  gives `0%`. The exact band table is centralized in `Building` for balance
  changes.
- `PowerReport.efficiency` remains the shared electrical efficiency. Each
  building's `Building.efficiency` is `PowerReport.efficiency ×
  Building.health_efficiency`, and mines/towers use this final value.
- The condition multiplier currently affects consumer work: mine income, tower
  damage, and tower attack speed. Damaged power plants and power nodes still
  use their full supply and transmission values; reducing infrastructure
  throughput by damage remains a later grid-damage rule.
- `BuildingSnapshot` adds optional `repair_cost` and `health_efficiency` fields
  (defaults `0` and `1.0` for
  manually constructed snapshots). Runtime snapshots always quote the full
  HP repair cost, even when the command is unavailable due to game state or
  insufficient gold. Existing `hp` and `max_hp` fields show actual health.
- Core health now lives on the `Core` entity. `GameState(..., core_hp=30)` and
  existing `core_hp` reads/assignments remain supported as a property over that
  same value. Custom starting HP above 30 raises the core's maximum to that
  starting value. Enemy arrivals, repairs, the status HUD, and building
  snapshots all use the same health. Zero core HP prevents repair even before
  `step()` records DEFEAT.
- HP repair leaves tower cooldowns, overload duration, debt and `needs_repair`
  unchanged. That existing flag is an **overload service fee**: settlement
  still charges 5 gold per flagged building and clears the flag without
  restoring HP. Buying HP repair does not cancel that fee.

The current GUI reads selected building HP and repair price from snapshots but
does not yet expose a repair button. A future control should call
`repair_building(building.id)` and display any `ValueError`. Enemy building
attacks still target only power nodes; health and repair interfaces are ready
for additional building targets.

## Selling and Targeting

Two command families extend the GUI-facing surface beyond build and repair.

- `sell_building(building_id) -> int` removes any non-core building and refunds
  `round(cost * 0.7)` gold, then refreshes the power grid. The core cannot be
  sold. The ID must be a positive integer (booleans rejected). Missing
  buildings, the core, a destroyed core, and ended games raise `ValueError`
  without changing state. Overload service markers and debt are untouched.
  The older `demolish_tower(building_id)` still removes a tower with no refund
  and no terminal-phase guard.
- `set_tower_target(tower_id, enemy_id) -> None` forces one tower to prefer a
  specific living enemy. The manual target wins only while it stays alive and
  inside the tower's range; otherwise the tower clears it and falls back to the
  default furthest-progressing enemy. `clear_tower_target(tower_id)` removes the
  manual target explicitly. Both validate positive-integer IDs (booleans
  rejected) and raise `ValueError` for missing towers, dead/missing enemies, a
  destroyed core, or an ended game, without changing state.

Every active enemy now carries a stable runtime `id`, assigned by `GameState`
when it spawns. `EnemySnapshot` exposes it as a required `id` field, and
`BuildingSnapshot` exposes `target_enemy_id` (default `None`) for towers. Tools
that construct these snapshots by hand must provide `EnemySnapshot.id`.

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
├── GAME_DESIGN.md          # Local gameplay design document
├── DEVELOPMENT_REPORT.md   # Local collaboration and integration notes
├── README.md               # Project structure and usage guide
├── requirements.txt        # GUI runtime dependencies
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
├── gui/
│   ├── gui.py              # Pygame entry point and main loop
│   ├── board_view.py       # Map, buildings, enemies and preview rendering
│   ├── sidebar.py          # Build controls and selected-cell details
│   ├── hud.py              # Status bar and event messages
│   ├── menu.py             # Start and level-selection screens
│   ├── styles.py           # Shared layout and colors
│   └── assets/             # Building sprites and review previews
└── tests/
    └── test_*.py           # Core rules and integration tests
```

## Run

Text demo:

```bash
python3 main.py
```

GUI:

```bash
python3 -m pip install -r requirements.txt
python3 gui/gui.py
```

The GUI requires `pygame-ce`, `pygame_gui`, and `python-i18n`. The core text
demo uses only the Python standard library.

## Test

```bash
python3 -m unittest discover -s tests
```

## Current Features

- 36 by 21 small-cell map with configurable rectangular building footprints.
- Fixed enemy route with continuous world-space movement and four enemy types.
- Buildable mines, power plants, power nodes, and three tower types.
- Radius-based power-grid connection and shared efficiency.
- Reduced building efficiency when power is insufficient or building health
  has dropped below its condition band.
- DAY/NIGHT lifecycle with explicit Start Night and wave settlement.
- Wave spawning, mine income, debt interest, kill rewards, and overload fees.
- Core overdraft, tower overload, wave intel, building repair, and selling.
- Manual tower targeting through stable enemy IDs.
- Building health, condition efficiency, and instant gold-funded repairs,
  including grid recovery.
- Text-based map rendering.
- Pygame GUI with map rendering, build preview, HUD, tower controls, intel,
  overdraft, and the DAY/NIGHT flow.

## Next Steps

The current prototype is smaller than the full V0.2 design. The main remaining
work is:

- Dynamic pathfinding and building-influenced route changes.
- Combat completion: cannon splash, armored damage reduction, enemy attacks on
  more building types, and saboteur route deviation.
- Eight-night progression and balance.
- Per-building power priority, time-scale controls, and richer wave intel.
- GUI follow-ups such as repair, sell, targeting controls, and attack/path
  visualization.

