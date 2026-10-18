"""Coverage for shared building health and gold-funded instant repairs."""

import unittest
from collections.abc import Callable

from grid_td.buildings import Core, Mine, Tower, create_building
from grid_td.enemies import create_enemy
from grid_td.game_state import GamePhase, GameState
from grid_td.map import create_demo_map
from grid_td.position import Position


BUILD_KINDS = (
    "mine", "power_plant", "power_node", "gun_tower", "cannon_tower", "slow_tower",
)


class BuildingHealthTest(unittest.TestCase):
    def test_every_building_has_independent_damage_and_repair_state(self) -> None:
        for kind in ("core",) + BUILD_KINDS:
            with self.subTest(kind=kind):
                factory = (
                    lambda building_id: Core(building_id, Position(0, 0))
                    if kind == "core"
                    else create_building(kind, building_id, Position(0, 0))
                )
                building = factory(1)
                other = factory(2)
                self.assertEqual(building.hp, building.max_hp)
                self.assertEqual(building.repair_cost, 0)

                building.take_damage(2)
                self.assertEqual(building.hp, building.max_hp - 2)
                self.assertEqual(building.repair_cost, 2)
                self.assertEqual(other.hp, other.max_hp)

                self.assertEqual(building.repair(), 2)
                self.assertEqual(building.hp, building.max_hp)
                self.assertEqual(building.repair(), 0)

                building.take_damage(building.max_hp + 10)
                self.assertEqual(building.hp, 0)
                self.assertTrue(building.is_destroyed)
                self.assertEqual(building.repair(), building.max_hp)
                self.assertFalse(building.is_destroyed)

    def test_damage_rejects_invalid_amounts_without_changing_health(self) -> None:
        building = create_building("power_node", 1, Position(0, 0))
        building.take_damage(1)
        for amount in (0, -1, True, False, 1.5, "2", None, float("nan")):
            with self.subTest(amount=amount):
                before = building.hp
                with self.assertRaises(ValueError):
                    building.take_damage(amount)
                self.assertEqual(building.hp, before)

    def test_destroyed_producers_and_towers_do_not_operate(self) -> None:
        for kind in ("mine", "gun_tower", "cannon_tower", "slow_tower"):
            with self.subTest(kind=kind):
                building = create_building(kind, 1, Position(0, 0))
                building.connected_to_grid = True
                building.efficiency = 1.0
                building.take_damage(building.hp)
                if isinstance(building, Mine):
                    self.assertEqual(building.collect_income(), 0)
                    building.repair()
                    self.assertEqual(building.collect_income(), building.income)
                elif isinstance(building, Tower):
                    self.assertFalse(building.can_attack())
                    building.repair()
                    self.assertTrue(building.can_attack())


class BuildingRepairTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game = GameState(create_demo_map())

    def assert_rejected_without_changes(self, operation: Callable[[], object]) -> None:
        game = self.game
        before = game.snapshot()
        identities = tuple(id(building) for building in game.buildings)
        next_id = game.next_building_id
        runner = game.wave_runner
        runner_state = (
            (runner.elapsed_seconds, runner.spawned_counts.copy())
            if runner is not None else None
        )
        timers = tuple(
            (building.cooldown_remaining, building.overload_seconds_remaining)
            for building in game.buildings if isinstance(building, Tower)
        )
        with self.assertRaises(ValueError):
            operation()
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(tuple(id(building) for building in game.buildings), identities)
        self.assertEqual(game.next_building_id, next_id)
        self.assertIs(game.wave_runner, runner)
        if runner is not None:
            self.assertEqual((runner.elapsed_seconds, runner.spawned_counts), runner_state)
        self.assertEqual(tuple(
            (building.cooldown_remaining, building.overload_seconds_remaining)
            for building in game.buildings if isinstance(building, Tower)
        ), timers)

    def test_paid_repair_supports_all_building_types_and_snapshot_quotes(self) -> None:
        for kind in ("core",) + BUILD_KINDS:
            with self.subTest(kind=kind):
                game = GameState(create_demo_map())
                building = (
                    game.building_at(game.grid_map.core_position)
                    if kind == "core" else game.build(
                        kind, Position(24, 15) if kind == "mine" else Position(30, 6)
                    )
                )
                building.take_damage(3)
                game.recalculate_power()
                before = game.snapshot()
                before_cell = game.cell_snapshot(building.position)
                self.assertEqual(before_cell.building.hp, building.max_hp - 3)
                self.assertEqual(before_cell.building.repair_cost, 3)

                self.assertEqual(game.repair_building(building.id), 3)

                after = game.snapshot()
                repaired = game.cell_snapshot(building.position).building
                self.assertEqual(after.status.gold, before.status.gold - 3)
                self.assertEqual(after.status.debt, before.status.debt)
                self.assertEqual(after.status.phase, before.status.phase)
                self.assertEqual(after.status.elapsed_seconds, before.status.elapsed_seconds)
                self.assertEqual(repaired.hp, repaired.max_hp)
                self.assertEqual(repaired.repair_cost, 0)
                self.assertEqual(before_cell.building.hp, building.max_hp - 3)
                for cell in building.occupied_cells():
                    self.assertEqual(game.cell_snapshot(cell).building, repaired)

    def test_day_and_night_repairs_do_not_advance_simulation(self) -> None:
        for phase in (GamePhase.DAY, GamePhase.NIGHT):
            with self.subTest(phase=phase):
                game = GameState(create_demo_map())
                tower = game.build("gun_tower", Position(30, 6))
                if phase == GamePhase.NIGHT:
                    game.start_next_wave()
                    game.step(0.05)
                tower.take_damage(1)
                game.overload_tower(tower.id)
                tower.cooldown_remaining = 0.75
                before = game.snapshot().status
                runner = game.wave_runner
                runner_elapsed = runner.elapsed_seconds if runner is not None else None
                enemies_before = tuple((enemy.hp, enemy.path_progress) for enemy in game.enemies)

                game.repair_building(tower.id)

                self.assertEqual(game.snapshot().status.phase, phase)
                self.assertEqual(game.elapsed_seconds, before.elapsed_seconds)
                self.assertEqual(game.debt, before.debt)
                self.assertTrue(tower.needs_repair)
                self.assertEqual(tower.cooldown_remaining, 0.75)
                self.assertEqual(tower.overload_seconds_remaining, 8.0)
                self.assertIs(game.wave_runner, runner)
                if runner is not None:
                    self.assertEqual(runner.elapsed_seconds, runner_elapsed)
                self.assertEqual(
                    tuple((enemy.hp, enemy.path_progress) for enemy in game.enemies),
                    enemies_before,
                )

    def test_zero_hp_buildings_can_be_repaired_without_replacing_occupancy(self) -> None:
        for kind in BUILD_KINDS:
            with self.subTest(kind=kind):
                game = GameState(create_demo_map())
                building = game.build(
                    kind, Position(24, 15) if kind == "mine" else Position(30, 6)
                )
                building.take_damage(building.hp)
                game.recalculate_power()
                next_id = game.next_building_id
                count = len(game.buildings)

                self.assertEqual(game.repair_building(building.id), building.max_hp)

                self.assertEqual(building.hp, building.max_hp)
                self.assertEqual(len(game.buildings), count)
                self.assertEqual(game.next_building_id, next_id)
                for cell in building.occupied_cells():
                    self.assertIs(game.building_at(cell), building)

    def test_saboteur_disabled_node_repair_immediately_restores_downstream_power(self) -> None:
        game = self.game
        node = game.build("power_node", Position(30, 9))
        tower = game.build("gun_tower", Position(30, 12))
        tower.cooldown_remaining = 999.0
        node.take_damage(node.hp - 1)
        saboteur = create_enemy("saboteur")
        saboteur.path_progress = 30.0
        game.start_next_wave()
        game.enemies = [saboteur]
        game.step(0.0)
        self.assertEqual(node.hp, 0)
        self.assertFalse(tower.connected_to_grid)
        gold_before = game.gold

        cost = game.repair_building(node.id)

        self.assertEqual(cost, node.max_hp)
        self.assertEqual(game.gold, gold_before - cost)
        self.assertTrue(node.connected_to_grid)
        self.assertTrue(tower.connected_to_grid)
        self.assertEqual(tower.efficiency, 1.0)
        self.assertEqual(game.snapshot().status.power.total_demand, tower.power_draw)

    def test_repair_restores_destroyed_plant_supply(self) -> None:
        plant = self.game.build("power_plant", Position(30, 6))
        plant.take_damage(plant.hp)
        self.game.recalculate_power()
        self.assertEqual(self.game.latest_power_report.total_supply, 10)
        self.game.repair_building(plant.id)
        self.assertEqual(self.game.latest_power_report.total_supply, 20)

    def test_core_arrival_damage_and_repair_share_one_health_value(self) -> None:
        game = self.game
        core = game.building_at(game.grid_map.core_position)
        game.start_next_wave()
        game.step(30.0)
        self.assertEqual(game.core_hp, 25)
        self.assertEqual(core.hp, game.core_hp)
        self.assertEqual(game.cell_snapshot(core.position).building.hp, game.core_hp)

        gold_before = game.gold
        self.assertEqual(game.repair_building(core.id), 5)
        snapshot = game.snapshot()
        self.assertEqual(game.gold, gold_before - 5)
        self.assertEqual(snapshot.status.core_hp, 30)
        self.assertEqual(game.cell_snapshot(core.position).building.hp, 30)
        self.assertEqual(core.hp, 30)

        game.core_hp = 12
        self.assertEqual(core.hp, 12)
        core.take_damage(2)
        self.assertEqual(game.snapshot().status.core_hp, 10)

    def test_custom_starting_core_health_preserves_constructor_compatibility(self) -> None:
        for health in (0, 1, 30, 100):
            with self.subTest(health=health):
                game = GameState(create_demo_map(), core_hp=health)
                core = game.building_at(game.grid_map.core_position)
                self.assertEqual(game.core_hp, health)
                self.assertEqual(core.hp, health)
                self.assertEqual(core.max_hp, max(30, health))

    def test_repair_with_exact_gold_spends_the_balance(self) -> None:
        node = self.game.build("power_node", Position(30, 9))
        node.take_damage(2)
        self.game.gold = 2
        self.assertEqual(self.game.repair_building(node.id), 2)
        self.assertEqual(self.game.gold, 0)

    def test_insufficient_gold_does_not_partially_repair_or_charge(self) -> None:
        node = self.game.build("power_node", Position(30, 9))
        node.take_damage(node.hp)
        self.game.recalculate_power()
        self.game.gold = node.max_hp - 1
        self.assert_rejected_without_changes(lambda: self.game.repair_building(node.id))

    def test_full_health_and_repeated_repairs_are_rejected_without_charging(self) -> None:
        tower = self.game.build("gun_tower", Position(30, 6))
        self.game.overload_tower(tower.id)
        self.assert_rejected_without_changes(lambda: self.game.repair_building(tower.id))
        tower.take_damage(1)
        self.game.repair_building(tower.id)
        self.assert_rejected_without_changes(lambda: self.game.repair_building(tower.id))

    def test_invalid_ids_and_demolished_buildings_are_rejected(self) -> None:
        tower = self.game.build("gun_tower", Position(30, 6))
        self.game.demolish_tower(tower.id)
        for building_id in (0, -1, True, False, 1.0, "1", None, 999, tower.id):
            with self.subTest(building_id=building_id):
                self.assert_rejected_without_changes(
                    lambda: self.game.repair_building(building_id)
                )

    def test_terminal_phases_and_result_messages_reject_repairs(self) -> None:
        node = self.game.build("power_node", Position(30, 9))
        node.take_damage(1)
        for phase, result in (
            (GamePhase.VICTORY, ""), (GamePhase.DEFEAT, ""),
            (GamePhase.DAY, "Victory. All waves cleared."),
        ):
            with self.subTest(phase=phase, result=result):
                self.game.phase = phase
                self.game.result_message = result
                self.assert_rejected_without_changes(lambda: self.game.repair_building(node.id))

    def test_zero_health_core_cannot_be_revived_before_or_after_defeat(self) -> None:
        core = self.game.building_at(self.game.grid_map.core_position)
        core.take_damage(core.hp)
        self.assertEqual(self.game.core_hp, 0)
        self.assert_rejected_without_changes(lambda: self.game.repair_building(core.id))
        self.game.step(0.0)
        self.assertEqual(self.game.phase, GamePhase.DEFEAT)
        self.assert_rejected_without_changes(lambda: self.game.repair_building(core.id))

    def test_settlement_keeps_hp_damage_and_overload_service_fee_separate(self) -> None:
        game = self.game
        tower = game.build("gun_tower", Position(30, 6))
        game.overload_tower(tower.id)
        tower.take_damage(2)
        game.repair_building(tower.id)
        tower.take_damage(1)
        game.start_next_wave()
        game.step(30.0)
        gold_before = game.gold
        interest = round(game.debt * 0.12)

        game.end_wave()

        self.assertEqual(game.gold, gold_before - interest - 5)
        self.assertFalse(tower.needs_repair)
        self.assertEqual(tower.hp, tower.max_hp - 1)
        self.assertEqual(game.cell_snapshot(tower.position).building.repair_cost, 1)


if __name__ == "__main__":
    unittest.main()
