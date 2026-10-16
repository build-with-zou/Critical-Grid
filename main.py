"""Run the minimal executable Critical Grid demo.

This module sits at the application entry layer. It assembles `GridMap`,
`GameState`, and `TextRenderer`, then drives one fixed sample defense layout.
Core rules should not live here: maps, buildings, waves, and state transitions
belong to the domain modules inside the `grid_td` package.

The public entry point is `main()`. `build_demo_defense()` only prepares a
fixed scenario for the demo. Simulation data flows through `GameState.step()`,
then the text renderer reads `GameState.snapshot()` for output. When changing
the demo layout, also check starting gold, mine-site restrictions, and
power-grid connectivity; otherwise the demo may raise `ValueError` during
startup.
"""

from grid_td.game_state import GamePhase, GameState
from grid_td.map import create_demo_map
from grid_td.position import Position
from grid_td.renderer import TextRenderer


def build_demo_defense(game: GameState) -> None:
    """Create a fixed defense layout that lets the demo run immediately.

    Args:
        game: Initialized game state. It owns building-cost and placement
            validation.

    Side effects:
        Calls `GameState.build()`, which spends gold, appends buildings, and
        recalculates the power grid. The coordinates and building kinds are
        part of the demo script, not a general build recommendation.
    """
    # Anchors use small cells; each former demo coordinate is multiplied by 3.
    game.build("power_plant", Position(30, 6))
    game.build("gun_tower", Position(30, 9))
    game.build("slow_tower", Position(30, 12))
    game.build("power_node", Position(30, 15))
    game.build("power_node", Position(27, 15))
    game.build("mine", Position(24, 15))


def main() -> None:
    """Run the text demo until victory, defeat, or the runtime guard fires.

    The demo explicitly starts each night after showing its planning day.
    Each combat loop advances one second of logical time. Wave spawning and
    tower/enemy interactions are handled by `GameState.step()`. Wave-end
    economic settlement and next-wave startup are called explicitly here so
    the demo keeps the state-machine boundary visible.
    """
    game = GameState(create_demo_map())
    renderer = TextRenderer()

    build_demo_defense(game)

    print("Minimal Grid Debt Tower Defense Prototype")
    print(renderer.render(game))

    while not game.snapshot().status.is_finished:
        if game.snapshot().status.phase == GamePhase.DAY:
            # A real frontend waits for the player's Start Night command here.
            # The non-interactive demo starts immediately after displaying DAY.
            game.start_next_wave()
            print(renderer.render(game))
        # The simulation layer uses float seconds for movement and cooldowns.
        game.step(1.0)
        status = game.snapshot().status

        if status.elapsed_seconds % 5 == 0:
            print(renderer.render(game))

        if status.waiting_for_next_wave:
            # WaveRunner only tracks spawning; GameState also waits for enemies to clear.
            print(game.end_wave())
            print(renderer.render(game))

        # This is a demo-script guard, not part of the game rules.
        if status.elapsed_seconds > 240:
            raise RuntimeError("Demo ran too long; check wave completion rules.")

    print(renderer.render(game))
    print(game.snapshot().status.result_message)


if __name__ == "__main__":
    main()

