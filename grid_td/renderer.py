"""Text state renderer.

This module belongs to the presentation layer. It projects the current
`GameState` into a readable string and should not mutate game data or advance
time. It depends on building-type `SYMBOL` values, map terrain queries, and
enemy route positions; `main.py` decides when to call `render()`.

Cell drawing has a defined priority: buildings cover enemies, enemies cover
routes, routes cover mine sites and high ground, and empty ground is last.
New renderable entities must account for that priority and for how
`BUILDING_SYMBOLS` uses subclass `isinstance()` matching.
"""

from __future__ import annotations

from grid_td.buildings import (
    CannonTower,
    Core,
    GunTower,
    Mine,
    PowerNode,
    PowerPlant,
    SlowTower,
)
from grid_td.game_state import GameState
from grid_td.position import Position


class TextRenderer:
    """Generate a plain-text snapshot with status line and character map."""

    BUILDING_SYMBOLS = {
        # Use types instead of strings to avoid duplicating the building kind map.
        Core: Core.SYMBOL,
        Mine: Mine.SYMBOL,
        PowerPlant: PowerPlant.SYMBOL,
        PowerNode: PowerNode.SYMBOL,
        GunTower: GunTower.SYMBOL,
        CannonTower: CannonTower.SYMBOL,
        SlowTower: SlowTower.SYMBOL,
    }

    def render(self, game: GameState) -> str:
        """Render the current game state.

        Returns:
            The first line is a wave, time, resource, and power summary. Later
            lines correspond to map rows. This method only reads state; calling
            it repeatedly on the same state should produce the same text.
        """
        rows = []
        enemy_positions = {
            enemy.position_on_route(game.grid_map.route)
            for enemy in game.enemies
            if enemy.is_alive
        }

        for y in range(game.grid_map.height):
            chars = []
            for x in range(game.grid_map.width):
                position = Position(x, y)
                building = game.building_at(position)

                if building is not None:
                    chars.append(self._building_symbol(building))
                elif position in enemy_positions:
                    chars.append("e")
                elif game.grid_map.is_route(position):
                    chars.append("=")
                elif game.grid_map.is_mine_site(position):
                    chars.append("m")
                elif game.grid_map.is_high_ground(position):
                    chars.append("^")
                else:
                    chars.append(".")

            rows.append("".join(chars))

        report = game.latest_power_report
        header = (
            f"Wave={game.current_wave_name} "
            f"Time={game.elapsed_seconds}s "
            f"Gold={game.gold} "
            f"Debt={game.debt} "
            f"CoreHP={game.core_hp} "
            f"Power={report.total_supply}/{report.total_demand} "
            f"Efficiency={report.efficiency:.0%}"
        )
        return header + "\n" + "\n".join(rows)

    def _building_symbol(self, building: object) -> str:
        """Return a display character by concrete building type, or `?`."""
        for building_type, symbol in self.BUILDING_SYMBOLS.items():
            if isinstance(building, building_type):
                return symbol
        return "?"

