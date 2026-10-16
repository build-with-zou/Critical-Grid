"""Minimal regression tests for the core loop.

These tests drive `GameState` directly and cover the most important
cross-module contracts in the current prototype: building should update the
power grid, core overdraft should increase both gold and debt, and the default
wave should advance without crashing. Tests use `create_demo_map()` as a fixed
fixture to avoid hiding real `PowerGrid`/`WaveRunner` collaboration behind
random maps or mocks.
"""

import unittest
from dataclasses import FrozenInstanceError

from grid_td.game_state import (
    CellSnapshot,
    GamePhase,
    GameSnapshot,
    GameState,
    GameStatus,
    PowerSnapshot,
)
from grid_td.map import create_demo_map
from grid_td.position import Position
from grid_td.renderer import TextRenderer


class CoreLoopTest(unittest.TestCase):
    """Verify core behavior when the state layer connects domain objects."""

    def test_building_updates_power_grid(self) -> None:
        """A plant and adjacent tower should connect and get positive efficiency."""
        game = GameState(create_demo_map())

        game.build("power_plant", Position(10, 2))
        tower = game.build("gun_tower", Position(10, 3))

        self.assertTrue(tower.connected_to_grid)
        self.assertGreater(tower.efficiency, 0)

    def test_disconnected_building_has_zero_efficiency(self) -> None:
        """A building outside the adjacent grid should render as unpowered."""
        game = GameState(create_demo_map())

        tower = game.build("gun_tower", Position(0, 1))

        self.assertFalse(tower.connected_to_grid)
        self.assertEqual(tower.efficiency, 0.0)
        self.assertEqual(game.latest_power_report.connected_count, 1)

    def test_power_shortage_reduces_connected_efficiency(self) -> None:
        """Connected demand above supply should lower shared efficiency."""
        game = GameState(create_demo_map())

        game.build("gun_tower", Position(10, 2))
        game.build("slow_tower", Position(10, 3))
        cannon = game.build("cannon_tower", Position(10, 4))

        report = game.latest_power_report
        self.assertEqual(report.total_supply, 10)
        self.assertEqual(report.total_demand, 12)
        self.assertAlmostEqual(report.efficiency, 10 / 12)
        self.assertAlmostEqual(cannon.efficiency, 10 / 12)

    def test_high_ground_increases_tower_range(self) -> None:
        """Building a tower on high ground should apply the range bonus."""
        game = GameState(create_demo_map())

        tower = game.build("gun_tower", Position(4, 2))

        self.assertEqual(tower.range, 3)

    def test_core_overdraft_adds_gold_and_debt(self) -> None:
        """Core overdraft should add both gold and debt."""
        game = GameState(create_demo_map())
        gold_before = game.gold

        game.core_overdraft(40)

        self.assertEqual(game.gold, gold_before + 40)
        self.assertGreater(game.debt, 0)

    def test_demolish_tower_updates_power_and_does_not_refund(self) -> None:
        game = GameState(create_demo_map())
        game.build("power_plant", Position(10, 2))
        tower = game.build("gun_tower", Position(10, 3))
        gold_before = game.gold

        removed = game.demolish_tower(tower.id)

        self.assertIs(removed, tower)
        self.assertIsNone(game.building_at(Position(10, 3)))
        self.assertEqual(game.latest_power_report.total_demand, 0)
        self.assertEqual(game.gold, gold_before)
        with self.assertRaises(ValueError):
            game.demolish_tower(tower.id)
        with self.assertRaises(ValueError):
            game.demolish_tower(game.building_at(Position(10, 1)).id)
            
    def test_buy_wave_intel_spends_gold_and_requires_gold(self) -> None:
        """Buying intel should expose the briefing and enforce its price."""
        game = GameState(create_demo_map())

        briefing = game.buy_wave_intel()

        self.assertEqual(briefing, "Basic enemies.")
        self.assertEqual(game.gold, 172)

        poor_game = GameState(create_demo_map(), gold=0)
        with self.assertRaises(ValueError):
            poor_game.buy_wave_intel()

    def test_overload_tower_marks_repair_and_adds_debt(self) -> None:
        """Tower overload should create the later repair/debt consequences."""
        game = GameState(create_demo_map())
        game.build("power_plant", Position(10, 2))
        tower = game.build("gun_tower", Position(10, 3))

        game.overload_tower(tower.id)

        self.assertTrue(tower.is_overloaded)
        self.assertTrue(tower.needs_repair)
        self.assertEqual(game.debt, 10)

        game.start_next_wave()
        game.step(30.0)
        game.end_wave()

        self.assertFalse(tower.needs_repair)

    def test_building_on_illegal_position(self) -> None:
        """Build placement rules should reject blocked or otherwise invalid cells."""
        game = GameState(create_demo_map())

        invalid_cases = (
            ("blocked terrain", "gun_tower", Position(0, 0)),
            ("enemy route", "gun_tower", Position(0, 4)),
            ("core position", "gun_tower", Position(10, 1)),
            ("mine outside mine site", "mine", Position(0, 1)),
            ("non-mine on mine site", "gun_tower", Position(2, 1)),
        )

        for label, kind, position in invalid_cases:
            with self.subTest(label=label, kind=kind, position=position):
                with self.assertRaises(ValueError):
                    game.build(kind, position)

        occupied_position = Position(10, 2)
        game.build("power_plant", occupied_position)

        with self.subTest(label="occupied position"):
            with self.assertRaises(ValueError):
                game.build("gun_tower", occupied_position)

    def test_building_requires_enough_gold(self) -> None:
        """Build placement should fail cleanly when the player cannot pay."""
        game = GameState(create_demo_map(), gold=0)

        with self.assertRaises(ValueError):
            game.build("gun_tower", Position(0, 1))

        self.assertIsNone(game.building_at(Position(0, 1)))

    def test_text_renderer_shows_illegal_ground(self) -> None:
        """Text rendering should expose blocked terrain for debugging and parity with GUI."""
        game = GameState(create_demo_map())
        rendered = TextRenderer().render(game)
        first_map_row = rendered.splitlines()[1]

        self.assertEqual(first_map_row, "##...##.....")

    def test_status_snapshot_exposes_gui_state(self) -> None:
        """The status snapshot should cover top-bar state without mutable entities."""
        game = GameState(create_demo_map())

        game.core_overdraft(40)
        status = game.status_snapshot()

        self.assertEqual(status.gold, 220)
        self.assertEqual(status.debt, 54)
        self.assertEqual(status.core_hp, 30)
        self.assertEqual(status.elapsed_seconds, 0)
        self.assertEqual(status.phase, GamePhase.DAY)
        self.assertEqual(status.wave_index, 0)
        self.assertEqual(status.current_wave_name, "Wave 1")
        self.assertFalse(status.waiting_for_next_wave)
        self.assertFalse(status.is_finished)
        self.assertEqual(status.result_message, "")
        self.assertEqual(status.power.connected_count, 1)
        self.assertEqual(status.power.total_supply, 10)
        self.assertEqual(status.power.total_demand, 0)
        self.assertEqual(status.power.efficiency, 1.0)

    def test_cell_snapshot_marks_terrain_buildings_and_enemies(self) -> None:
        """A cell snapshot should combine terrain, occupants, and display priority."""
        game = GameState(create_demo_map())

        illegal_cell = game.cell_snapshot(Position(0, 0))

        self.assertEqual(illegal_cell.terrain, "illegal")
        self.assertFalse(illegal_cell.is_buildable)
        self.assertIsNone(illegal_cell.building)
        self.assertEqual(illegal_cell.display_symbol, "#")

        game.build("power_plant", Position(10, 2))
        building_cell = game.cell_snapshot(Position(10, 2))

        self.assertEqual(building_cell.terrain, "empty")
        self.assertFalse(building_cell.is_buildable)
        self.assertEqual(building_cell.building.kind, "power_plant")
        self.assertEqual(building_cell.building.symbol, "P")
        self.assertTrue(building_cell.building.connected_to_grid)
        self.assertEqual(building_cell.display_symbol, "P")

        game.start_next_wave()
        game.step(0.0)
        route_cell = game.cell_snapshot(Position(0, 4))

        self.assertEqual(route_cell.terrain, "route")
        self.assertTrue(route_cell.has_enemy)
        self.assertEqual(route_cell.enemy_count, 1)
        self.assertEqual(route_cell.enemies[0].name, "Basic")
        self.assertEqual(route_cell.display_symbol, "e")

    def test_board_snapshot_matches_map_size_and_is_read_only(self) -> None:
        """The board snapshot should be immutable enough for presentation code."""
        game = GameState(create_demo_map())

        snapshot = game.snapshot()

        self.assertEqual(snapshot.width, 12)
        self.assertEqual(snapshot.height, 7)
        self.assertEqual(len(snapshot.board), 7)
        self.assertTrue(all(len(row) == 12 for row in snapshot.board))
        self.assertIsInstance(snapshot.board, tuple)
        self.assertIsInstance(snapshot.board[0], tuple)
        self.assertEqual(snapshot.board[0][0].terrain, "illegal")
        with self.assertRaises(FrozenInstanceError):
            snapshot.board[0][0].terrain = "empty"

    def test_cell_snapshot_rejects_out_of_bounds_position(self) -> None:
        """Single-cell reads should fail clearly for invalid GUI coordinates."""
        game = GameState(create_demo_map())

        with self.assertRaises(ValueError):
            game.cell_snapshot(Position(-1, 0))

    def test_text_renderer_uses_snapshot_contract_only(self) -> None:
        """Text rendering should not depend on GameState's mutable attributes."""
        snapshot = GameSnapshot(
            width=2,
            height=1,
            cell_size=1.0,
            distance_metric="manhattan",
            status=GameStatus(
                phase=GamePhase.NIGHT,
                gold=1,
                debt=2,
                core_hp=9,
                elapsed_seconds=3,
                wave_index=0,
                current_wave_name="Test Wave",
                waiting_for_next_wave=False,
                is_finished=False,
                result_message="",
                power=PowerSnapshot(
                    connected_count=1,
                    total_supply=4,
                    total_demand=5,
                    efficiency=0.8,
                ),
            ),
            board=(
                (
                    CellSnapshot(Position(0, 0), "empty", True, None, ()),
                    CellSnapshot(Position(1, 0), "illegal", False, None, ()),
                ),
            ),
        )

        class SnapshotOnlyGame:
            """Minimal stand-in proving the renderer only needs snapshot()."""

            def snapshot(self) -> GameSnapshot:
                return snapshot

        rendered = TextRenderer().render(SnapshotOnlyGame())

        self.assertEqual(
            rendered,
            "Phase=night Wave=Test Wave Time=3s Gold=1 Debt=2 CoreHP=9 Power=4/5 Efficiency=80%\n.#",
        )

    def test_waiting_for_next_wave_requires_spawn_complete_and_no_enemies(self) -> None:
        """Wave settlement should wait for both spawning and enemy cleanup."""
        game = GameState(create_demo_map())

        self.assertFalse(game.waiting_for_next_wave)

        game.start_next_wave()
        game.step(8.0)

        self.assertTrue(game.wave_runner.is_complete)
        self.assertGreater(len(game.enemies), 0)
        self.assertFalse(game.waiting_for_next_wave)

        game.step(20.0)

        self.assertEqual(game.enemies, [])
        self.assertTrue(game.waiting_for_next_wave)

    def test_end_wave_and_start_next_wave_transition(self) -> None:
        """Wave settlement should advance the index and restart the runner."""
        game = GameState(create_demo_map())

        game.start_next_wave()
        game.step(30.0)
        message = game.end_wave()

        self.assertIn("Wave ended.", message)
        self.assertEqual(game.wave_index, 1)
        self.assertIsNone(game.wave_runner)
        self.assertEqual(game.current_wave_name, "Wave 2")

        game.start_next_wave()

        self.assertIsNotNone(game.wave_runner)
        self.assertEqual(game.current_wave_name, "Wave 2")

    def test_step_does_not_advance_finished_game(self) -> None:
        """A finished game should ignore future simulation steps."""
        game = GameState(create_demo_map())
        game.result_message = "Victory. All waves cleared."

        game.step(1.0)

        self.assertEqual(game.elapsed_seconds, 0)
        self.assertEqual(game.enemies, [])

    def test_step_accumulates_fractional_logical_time(self) -> None:
        """Small fixed steps should advance every subsystem by exact float time."""
        game = GameState(create_demo_map())
        game.start_next_wave()

        for _ in range(20):
            game.step(0.05)

        self.assertAlmostEqual(game.elapsed_seconds, 1.0)
        self.assertAlmostEqual(game.wave_runner.elapsed_seconds, 1.0)

    def test_step_rejects_invalid_durations_without_changing_state(self) -> None:
        """Invalid deltas must not partially advance the clock or wave runner."""
        invalid_durations = (
            -0.05,
            True,
            False,
            "0.05",
            None,
            float("nan"),
            float("inf"),
            -float("inf"),
            10**1000,
        )

        for seconds in invalid_durations:
            with self.subTest(seconds=seconds):
                game = GameState(create_demo_map())
                game.start_next_wave()
                before = game.snapshot()
                runner = game.wave_runner
                with self.assertRaises(ValueError):
                    game.step(seconds)

                self.assertEqual(game.snapshot(), before)
                self.assertIs(game.wave_runner, runner)
                self.assertEqual(runner.elapsed_seconds, 0.0)

    def test_demo_wave_can_advance_without_crashing(self) -> None:
        """The default map and basic defense should run for multiple steps."""
        game = GameState(create_demo_map())
        game.build("power_plant", Position(10, 2))
        game.build("gun_tower", Position(10, 3))

        game.start_next_wave()
        for _ in range(20):
            game.step(1.0)

        self.assertGreaterEqual(game.core_hp, 0)


if __name__ == "__main__":
    unittest.main()

