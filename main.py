from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position
from grid_td.renderer import TextRenderer


def build_demo_defense(game: GameState) -> None:
    """Build a tiny scripted layout so the prototype can run immediately."""
    game.build("power_plant", Position(10, 2))
    game.build("gun_tower", Position(10, 3))
    game.build("slow_tower", Position(10, 4))
    game.build("power_node", Position(10, 5))
    game.build("power_node", Position(9, 5))
    game.build("mine", Position(8, 5))


def main() -> None:
    game = GameState(create_demo_map())
    renderer = TextRenderer()

    build_demo_defense(game)

    print("Minimal Grid Debt Tower Defense Prototype")
    print(renderer.render(game))

    while not game.is_finished:
        game.step(1.0)

        if game.elapsed_seconds % 5 == 0:
            print(renderer.render(game))

        if game.waiting_for_next_wave:
            print(game.end_wave())
            if not game.is_finished:
                game.start_next_wave()

        if game.elapsed_seconds > 240:
            raise RuntimeError("Demo ran too long; check wave completion rules.")

    print(renderer.render(game))
    print(game.result_message)


if __name__ == "__main__":
    main()

