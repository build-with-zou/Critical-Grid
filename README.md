# Critical Grid

Critical Grid is a minimalist grid-based tower defense prototype built in Python.

The current goal is not to build a full commercial game. Instead, this project starts with a clear, runnable, object-oriented core so the game rules can be learned, tested, and expanded step by step.

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

