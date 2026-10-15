"""Text state renderer.

This module belongs to the presentation layer. It projects the current
`GameState` into a readable string and should not mutate game data or advance
time. It reads through `GameState.snapshot()`, so text output and future GUI
views share the same presentation contract; `main.py` decides when to call
`render()`.

Cell drawing priority lives in `CellSnapshot.display_symbol`: buildings cover
enemies, enemies cover routes, routes cover mine sites, high ground, blocked
terrain, and empty ground. New renderable entities should update the snapshot
contract first, then this renderer can stay a thin projection.
"""

from __future__ import annotations

from grid_td.game_state import GameState


class TextRenderer:
    """Generate a plain-text snapshot with status line and character map."""

    def render(self, game: GameState) -> str:
        """Render the current game state.

        Returns:
            The first line is a wave, time, resource, and power summary. Later
            lines correspond to map rows. This method only reads state; calling
            it repeatedly on the same state should produce the same text.
        """
        snapshot = game.snapshot()
        status = snapshot.status
        report = status.power
        rows = ["".join(cell.display_symbol for cell in row) for row in snapshot.board]
        # Keep whole-second demos compact while preserving fractional time for
        # fixed-step simulations such as 0.05-second updates.
        elapsed = f"{status.elapsed_seconds:g}"
        header = (
            f"Wave={status.current_wave_name} "
            f"Time={elapsed}s "
            f"Gold={status.gold} "
            f"Debt={status.debt} "
            f"CoreHP={status.core_hp} "
            f"Power={report.total_supply}/{report.total_demand} "
            f"Efficiency={report.efficiency:.0%}"
        )
        return header + "\n" + "\n".join(rows)

