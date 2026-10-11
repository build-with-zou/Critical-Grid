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
    BUILDING_SYMBOLS = {
        Core: Core.SYMBOL,
        Mine: Mine.SYMBOL,
        PowerPlant: PowerPlant.SYMBOL,
        PowerNode: PowerNode.SYMBOL,
        GunTower: GunTower.SYMBOL,
        CannonTower: CannonTower.SYMBOL,
        SlowTower: SlowTower.SYMBOL,
    }

    def render(self, game: GameState) -> str:
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
        for building_type, symbol in self.BUILDING_SYMBOLS.items():
            if isinstance(building, building_type):
                return symbol
        return "?"

