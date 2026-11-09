"""Constructor validation, list setters, and test-only state invariants."""

import unittest

from grid_td.buildings import Core, GunTower
from grid_td.enemies import create_enemy
from grid_td.game_state import GameState
from grid_td.map import create_demo_map
from grid_td.position import Position
from grid_td.waves import Wave


class ConstructorValidationTest(unittest.TestCase):
    def test_rejects_invalid_resources(self) -> None:
        grid_map = create_demo_map()
        invalid = (
            {"gold": -1},
            {"debt": -1},
            {"core_hp": -1},
            {"gold": 1.5},
            {"debt": True},
            {"core_hp": False},
            {"elapsed_seconds": -0.1},
            {"elapsed_seconds": float("nan")},
            {"elapsed_seconds": float("inf")},
            {"intel_price": -1},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    GameState(grid_map, **kwargs)

    def test_rejects_wrong_collection_types_and_elements(self) -> None:
        game = GameState(create_demo_map())
        tower = game.build("gun_tower", Position(0, 3))
        enemy = create_enemy("basic")

        cases = (
            {"buildings": (tower,)},
            {"buildings": ["tower"]},
            {"buildings": [Core(1, Position(0, 0))]},
            {"buildings": [GunTower(1, Position(0, 3)), GunTower(1, Position(3, 3))]},
            {"enemies": (enemy,)},
            {"enemies": ["enemy"]},
            {"waves": [Wave("Test", "", ())]},
            {"waves": (object(),)},
        )
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    GameState(create_demo_map(), **kwargs)

    def test_rejects_duplicate_assigned_enemy_ids(self) -> None:
        first = create_enemy("basic")
        first.id = 5
        second = create_enemy("basic")
        second.id = 5

        with self.assertRaises(ValueError):
            GameState(create_demo_map(), enemies=[first, second])

    def test_normalizes_id_counters_above_injected_entities(self) -> None:
        building = GunTower(50, Position(0, 3))
        first = create_enemy("basic")
        second = create_enemy("basic")

        game = GameState(
            create_demo_map(),
            buildings=[building],
            enemies=[first, second],
        )

        core = next(entity for entity in game.buildings if isinstance(entity, Core))
        self.assertEqual(core.id, 51)
        self.assertEqual(game.next_building_id, 52)
        self.assertEqual(game.next_enemy_id, 1)
        game.validate_state()


class ListSetterValidationTest(unittest.TestCase):
    def test_enemy_setter_rejects_duplicate_assigned_ids(self) -> None:
        game = GameState(create_demo_map())
        first = create_enemy("basic")
        first.id = 7
        second = create_enemy("basic")
        second.id = 7

        with self.assertRaises(ValueError):
            game.enemies = [first, second]

    def test_enemy_setter_allows_test_fixture_zero_ids(self) -> None:
        game = GameState(create_demo_map())

        game.enemies = [create_enemy("basic"), create_enemy("basic")]

        self.assertIsNone(game.validate_state())

    def test_building_setter_rejects_foreign_core(self) -> None:
        game = GameState(create_demo_map())

        with self.assertRaises(ValueError):
            game.buildings = [Core(999, Position(0, 0))]

    def test_wave_setter_rejects_non_tuple_values(self) -> None:
        game = GameState(create_demo_map())

        with self.assertRaises(ValueError):
            game.waves = [Wave("Test", "", ())]


class ValidateStateTest(unittest.TestCase):
    def test_passes_after_normal_core_flow(self) -> None:
        game = GameState(create_demo_map())
        game.build("gun_tower", Position(30, 6))
        game.start_next_wave()
        game.step(0.05)
        game.step(30.0)
        game.end_wave()

        self.assertIsNone(game.validate_state())

    def test_detects_tampered_id_counter(self) -> None:
        game = GameState(create_demo_map())

        game.next_building_id = 1

        with self.assertRaises(AssertionError):
            game.validate_state()

    def test_detects_duplicate_building_ids(self) -> None:
        game = GameState(create_demo_map())
        core = next(entity for entity in game.buildings if isinstance(entity, Core))

        game._buildings.append(GunTower(core.id, Position(0, 3)))

        with self.assertRaises(AssertionError):
            game.validate_state()


if __name__ == "__main__":
    unittest.main()
