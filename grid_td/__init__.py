"""Core rules package for Critical Grid.

This package sits between the application entry point and concrete domain
objects. It provides pure Python game logic that `main.py` or tests can drive
directly. The main modules cover maps and coordinates, buildings and enemies,
wave generation, power-grid calculation, global state, and text rendering.
There are currently no package-level re-exports; callers should import public
types from their specific submodules.

The typical call graph has `GameState` composing `GridMap`, `Building`,
`Enemy`, `PowerGrid`, and `WaveRunner`, while `TextRenderer` reads
`GameState` to produce output. Some objects in these modules are mutable,
especially building power-connection and efficiency fields; prefer changing
those fields through the existing `GameState` or `PowerGrid` entry points.
"""

