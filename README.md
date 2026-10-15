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

`GameState.step(seconds)` is the simulation boundary. Each step spawns due
enemies, recalculates power, lets connected towers attack, then advances
enemies toward the core. Wave settlement is separate: `end_wave()` applies
mine income, debt interest, and repair costs, while `start_next_wave()` creates
the next spawn runner.

Presentation layers should read through `GameState.snapshot()` rather than
accessing mutable state lists and counters directly. The snapshot contains a
status object plus a row-major board of cell snapshots, so both text and GUI
frontends can render the same source of truth.

The current Python prototype is intentionally smaller than
`GAME_DESIGN.md`: the power grid connects buildings through directly adjacent
occupied cells, the demo contains four waves, routing is fixed, and building
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

The first wave runner is created automatically by `GameState(...)`. After each
step, use the snapshot to check whether the wave can be settled:

```python
if game.snapshot().status.waiting_for_next_wave:
    message = game.end_wave()
    if not game.snapshot().status.is_finished:
        game.start_next_wave()
```

- `waiting_for_next_wave` is true only while the game is unfinished, the core
  is alive, spawning is complete, and no enemies remain.
- `end_wave()` returns a settlement string. It pays mine income, charges
  interest and repairs, clears repair markers, advances the wave index, and
  removes the runner exactly once. Settling the final wave records victory.
- `start_next_wave()` returns `None` and creates the next runner only after
  settlement. It cannot restart an active or cleared-but-unsettled wave.
- Both commands raise `ValueError` for invalid transitions, including calls
  after victory or defeat, and leave state unchanged on rejection. Defeat is
  recorded by `step()` and is not followed by wave settlement.

The normal text/GUI call sequence is unchanged. Frontends that expose these
commands directly should catch `ValueError` and display its message.

## Simulation Clock

`GameState` owns the authoritative logical clock. Each call to
`game.step(seconds)` advances that same finite, non-negative delta through the
wave scheduler, tower cooldowns, overload timers, enemy movement, and
`elapsed_seconds`. A fixed-step caller can use `0.05` seconds for 20 logical
updates per second; the core does not start its own timer or event loop.

`elapsed_seconds` is a float so fractional steps accumulate without integer
rounding. `step(0)` remains valid and processes events scheduled at
logical time zero. Invalid durations, including negative, non-finite, boolean,
string, and unrepresentably large values, raise `ValueError` without changing
state.

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
│   ├── position.py         # Grid position object
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

- Grid-based map.
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

