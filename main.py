"""Run the minimal executable Critical Grid demo.

This module sits at the application entry layer. It loads a level definition,
assembles `GameState` and `TextRenderer`, then drives one fixed sample defense
layout. Core rules should not live here: maps, buildings, waves, and state
transitions belong to the domain modules inside the `grid_td` package.

The public entry point is `main()`. `build_demo_defense()` only prepares a
fixed scenario for the demo. Simulation data flows through `GameState.step()`,
then the text renderer reads `GameState.snapshot()` for output. When changing
the demo layout, also check starting gold, mine-site restrictions, and
power-grid connectivity; otherwise the demo may raise `ValueError` during
startup.
"""

from grid_td.game_state import GamePhase, GameState
from grid_td.levels import load_demo_level
from grid_td.position import Position
from grid_td.renderer import TextRenderer


DEMO_REINFORCEMENTS: tuple[tuple[str, Position], ...] = (
    ("gun_tower", Position(30, 9)),
    ("power_node", Position(18, 6)),
    ("cannon_tower", Position(15, 6)),
    ("cannon_tower", Position(33, 0)),
    ("gun_tower", Position(33, 3)),
    ("power_node", Position(27, 9)),
    ("power_node", Position(30, 12)),
    ("power_plant", Position(30, 15)),
    ("cannon_tower", Position(27, 15)),
    ("gun_tower", Position(30, 18)),
    ("cannon_tower", Position(18, 12)),
    ("gun_tower", Position(12, 3)),
    ("power_plant", Position(33, 12)),
    ("cannon_tower", Position(27, 18)),
    ("cannon_tower", Position(21, 15)),
    ("gun_tower", Position(18, 18)),
    ("cannon_tower", Position(15, 15)),
    ("gun_tower", Position(33, 18)),
)


def build_demo_defense(game: GameState) -> None:
    """Create an initial defense that covers both enemy entrances.

    Args:
        game: Initialized game state. It owns building-cost and placement
            validation.

    Side effects:
        Calls `GameState.build()`, which spends gold, appends buildings, and
        recalculates the power grid. The coordinates and building kinds are
        part of the demo script, not a general build recommendation.
    """
    # The high-ground cannon covers the primary road; the core crown covers
    # both the primary and southeast approaches.
    game.build("power_plant", Position(30, 6))
    game.build("power_node", Position(24, 6))
    game.build("cannon_tower", Position(21, 6))
    game.build("gun_tower", Position(24, 12))
    game.build("gun_tower", Position(30, 0))
    # Extend power to the far mine so the demo can show settlement income.
    game.build("power_node", Position(24, 9))
    game.build("mine", Position(24, 15))


def maintain_demo_defense(game: GameState) -> None:
    """Repair damage and spend settlement income on the next demo towers.

    The text demo is not a player, so it uses a fixed reinforcement list. Builds
    that are too expensive are retried after the next settlement; invalid
    placements are skipped. This is demo-script policy, not a core rule.
    """
    for building in list(game.buildings):
        if building.repair_cost > 0:
            try:
                game.repair_building(building.id)
            except ValueError:
                pass

    for kind, position in DEMO_REINFORCEMENTS:
        if game.building_at(position) is not None:
            continue
        try:
            game.build(kind, position)
        except ValueError as error:
            if "Not enough gold" in str(error):
                break


def main() -> None:
    """Run the text demo until victory, defeat, or the runtime guard fires.

    The demo explicitly starts each night after showing its planning day.
    Each combat loop advances one second of logical time. Wave spawning and
    tower/enemy interactions are handled by `GameState.step()`. Wave-end
    economic settlement and next-wave startup are called explicitly here so
    the demo keeps the state-machine boundary visible.
    """
    game = GameState.from_level(load_demo_level())
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
            if not game.snapshot().status.is_finished:
                maintain_demo_defense(game)
            print(renderer.render(game))

        # This is a demo-script guard, not part of the game rules.
        if status.elapsed_seconds > 600:
            raise RuntimeError("Demo ran too long; check wave completion rules.")

    print(renderer.render(game))
    print(game.snapshot().status.result_message)


if __name__ == "__main__":
    main()

