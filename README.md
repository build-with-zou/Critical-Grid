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
  -> TextRenderer                 read-only text projection of GameState
```

`GameState.step(seconds)` is the simulation boundary. Each step spawns due
enemies, recalculates power, lets connected towers attack, then advances
enemies toward the core. Wave settlement is separate: `end_wave()` applies
mine income, debt interest, and repair costs, while `start_next_wave()` creates
the next spawn runner.

The current Python prototype is intentionally smaller than
`GAME_DESIGN.md`: the power grid connects buildings through directly adjacent
occupied cells, the demo contains four waves, routing is fixed, and building
health/damage is not yet modeled as mutable state. Treat the code as the
behavioral source of truth when changing the prototype; use the design document
for planned features and unresolved rules.

Recommended reading order:

1. `main.py` for the runnable scenario.
2. `grid_td/game_state.py` for orchestration and state transitions.
3. `grid_td/buildings.py`, `grid_td/enemies.py`, and `grid_td/waves.py` for
   domain behavior.
4. `grid_td/power_grid.py` for connectivity and efficiency side effects.
5. `grid_td/map.py`, `grid_td/position.py`, and `grid_td/renderer.py` for
   supporting rules and output.
6. `tests/test_core_loop.py` for the currently protected behavior.

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

