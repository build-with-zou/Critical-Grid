"""Regression coverage for world geometry, footprint placement and power."""

import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

from grid_td.buildings import CannonTower, Core, GunTower, Mine, PowerNode
from grid_td.enemies import Enemy, create_enemy
from grid_td.game_state import GamePhase, GameState
from grid_td.map import GridMap, create_demo_map
from grid_td.path import RoutePath
from grid_td.position import Footprint, Position, WorldPosition, world_distance
from grid_td.power_grid import PowerGrid


def empty_map() -> GridMap:
    """Keep placement cases independent of the demo's fixed terrain."""
    return GridMap(
        width=20, height=20,
        route=(Position(0, 18), Position(19, 18)),
        core_position=Position(10, 10),
        mine_positions=frozenset(), high_ground_positions=frozenset(),
        illegal_ground_positions=frozenset(),
        road_cells=frozenset(Position(x, 18) for x in range(20)),
    )


class WorldGeometryTest(unittest.TestCase):
    def test_cell_coordinates_and_even_footprint_centers(self) -> None:
        self.assertEqual(Position(2, 3).center, WorldPosition(2.5, 3.5))
        self.assertEqual(WorldPosition(2.99, 3.01).cell, Position(2, 3))
        self.assertEqual(WorldPosition(-0.01, -1.01).cell, Position(-1, -2))
        footprint = Footprint(2, 4)
        self.assertEqual(footprint.center(Position(3, 5)), WorldPosition(4, 7))
        self.assertEqual(len(footprint.cells(Position(3, 5))), 8)
        self.assertFalse(footprint.contains(Position(3, 5), Position(5, 5)))
        self.assertEqual(world_distance(WorldPosition(0, 0), WorldPosition(3, 4)), 7)

    def test_invalid_geometry_is_rejected(self) -> None:
        for width, height in ((0, 3), (-1, 3), (True, 3), (3, 1.5)):
            with self.subTest(size=(width, height)), self.assertRaises(ValueError):
                Footprint(width, height)
        for value in (True, 1.5, "2"):
            with self.subTest(coordinate=value), self.assertRaises(ValueError):
                Position(value, 0)
        for value in (True, "2", float("nan"), float("inf"), 10**1000):
            with self.subTest(coordinate=value), self.assertRaises(ValueError):
                WorldPosition(value, 0)

    def test_route_sampling_is_independent_of_waypoint_spacing(self) -> None:
        sparse = RoutePath((WorldPosition(0.5, 0.5), WorldPosition(6.5, 0.5),
                            WorldPosition(6.5, 3.5)))
        dense = RoutePath((WorldPosition(0.5, 0.5), WorldPosition(2.5, 0.5),
                           WorldPosition(6.5, 0.5), WorldPosition(6.5, 3.5)))
        self.assertEqual(sparse.length, 9)
        for distance in (-1, 0, 0.25, 2, 5.99, 6, 7.5, 9, 100):
            with self.subTest(distance=distance):
                self.assertEqual(sparse.position_at(distance), dense.position_at(distance))
        self.assertEqual(sparse.position_at(7.5), WorldPosition(6.5, 2))
        singleton = RoutePath((WorldPosition(1, 2),))
        self.assertEqual(singleton.position_at(100), WorldPosition(1, 2))
        self.assertEqual(singleton.length, 0)

    def test_invalid_routes_are_rejected(self) -> None:
        for points in ((), (WorldPosition(0, 0), WorldPosition(0, 0)),
                       (WorldPosition(0, 0), WorldPosition(1, 1))):
            with self.subTest(points=points), self.assertRaises(ValueError):
                RoutePath(points)

    def test_sparse_custom_roads_reserve_every_traversed_cell(self) -> None:
        grid_map = replace(empty_map(), road_cells=None)
        self.assertTrue(grid_map.is_route(Position(7, 18)))
        self.assertTrue(grid_map.is_buildable(Position(7, 18)))
        with self.assertRaises(ValueError):
            replace(grid_map, road_cells=frozenset(grid_map.route))
        for changes in ({"width": 0}, {"route": ()},
                        {"core_position": Position(19, 19)},
                        {"route": (Position(0, 0), Position(1, 1))}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(grid_map, **changes)

    def test_path_captures_mutable_waypoint_input(self) -> None:
        points = [WorldPosition(0, 0), WorldPosition(3, 0)]
        path = RoutePath(points)
        points[1] = WorldPosition(6, 0)
        self.assertEqual(path.length, 3)
        self.assertEqual(path.position_at(3), WorldPosition(3, 0))

    def test_demo_map_preserves_terrain_width_and_travel_time(self) -> None:
        grid_map = create_demo_map()
        self.assertEqual((grid_map.width, grid_map.height), (36, 21))
        self.assertEqual(grid_map.path.length, 36)
        self.assertEqual(len(grid_map.route_cells), 13 * 9)
        self.assertTrue(all(grid_map.is_route(Position(7, y)) for y in (12, 13, 14)))
        self.assertFalse(grid_map.is_route(Position(7, 11)))
        self.assertTrue(grid_map.is_mine_site(Position(8, 5)))
        self.assertTrue(grid_map.is_core(Position(32, 5)))
        for kind, old_speed in (("basic", 0.75), ("fast", 1.25),
                                ("armored", 0.45), ("saboteur", 0.85)):
            with self.subTest(kind=kind):
                enemy = create_enemy(kind)
                self.assertEqual(enemy.speed, old_speed * 3)
                self.assertAlmostEqual(grid_map.path.length / enemy.speed, 12 / old_speed)
                enemy.advance(1.0)
                self.assertAlmostEqual(enemy.path_progress, old_speed * 3)
                self.assertEqual(enemy.world_position_on_route(grid_map.path),
                                 WorldPosition(1.5 + old_speed * 3, 13.5))

    def test_arrival_uses_distance_instead_of_waypoint_count(self) -> None:
        path = create_demo_map().path
        enemy = create_enemy("basic")
        enemy.path_progress = 35.99
        self.assertFalse(enemy.has_reached_core(path))
        enemy.path_progress = 36
        self.assertTrue(enemy.has_reached_core(path))
        self.assertEqual(enemy.position_on_route(path), Position(28, 4))


class FootprintPlacementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game = GameState(empty_map(), gold=1000)

    def assert_rejected(self, kind: str, anchor: Position) -> None:
        before = self.game.snapshot()
        next_id = self.game.next_building_id
        preview = self.game.preview_build(kind, anchor)
        self.assertFalse(preview.is_valid)
        self.assertTrue(preview.reason)
        with self.assertRaisesRegex(ValueError, ".+") as rejection:
            self.game.build(kind, anchor)
        self.assertEqual(str(rejection.exception), preview.reason)
        self.assertEqual(self.game.snapshot(), before)
        self.assertEqual(self.game.next_building_id, next_id)

    def test_unaligned_placement_occupies_and_releases_all_cells(self) -> None:
        anchor = Position(1, 2)
        before = self.game.snapshot()
        preview = self.game.preview_build("gun_tower", anchor)
        self.assertTrue(preview.is_valid)
        self.assertEqual(preview.reason, "")
        self.assertEqual((preview.width, preview.height), (3, 3))
        self.assertEqual(self.game.snapshot(), before)
        with self.assertRaises(FrozenInstanceError):
            preview.width = 4
        tower = self.game.build("gun_tower", anchor)
        self.assertEqual(tower.position, anchor)
        self.assertEqual(tower.center, WorldPosition(2.5, 3.5))
        for cell in preview.occupied_cells:
            self.assertIs(self.game.building_at(cell), tower)
            snapshot = self.game.cell_snapshot(cell)
            self.assertEqual(snapshot.building.id, tower.id)
            self.assertEqual(snapshot.building.position, anchor)
            self.assertEqual((snapshot.building.width, snapshot.building.height), (3, 3))
            self.assertEqual(snapshot.building.center, tower.center)
            self.assertFalse(snapshot.is_buildable)
        self.assertIsNone(self.game.building_at(Position(4, 2)))
        self.game.demolish_tower(tower.id)
        for cell in preview.occupied_cells:
            self.assertIsNone(self.game.building_at(cell))
        self.assertTrue(self.game.preview_build("gun_tower", anchor).is_valid)

    def test_non_anchor_overlap_and_partial_out_of_bounds_are_rejected(self) -> None:
        self.game.build("gun_tower", Position(1, 2))
        for anchor in (Position(3, 4), Position(0, 1), Position(18, 0),
                       Position(0, 18), Position(-1, 0), Position(12, 12)):
            with self.subTest(anchor=anchor):
                self.assert_rejected("gun_tower", anchor)
        self.assertTrue(self.game.preview_build("gun_tower", Position(17, 0)).is_valid)

    def test_terrain_is_checked_under_the_entire_footprint(self) -> None:
        self.game.grid_map = replace(
            self.game.grid_map,
            illegal_ground_positions=frozenset({Position(4, 4), Position(1, 18)}),
        )
        self.assert_rejected("gun_tower", Position(2, 2))
        self.assert_rejected("gun_tower", Position(0, 16))
        # A free anchor alone cannot guarantee a complete footprint will fit.
        self.assertTrue(self.game.cell_snapshot(Position(2, 2)).is_buildable)

    def test_mine_footprint_must_fit_inside_the_resource_area(self) -> None:
        mine_cells = frozenset(Footprint(3, 3).cells(Position(1, 2)))
        self.game.grid_map = replace(self.game.grid_map, mine_positions=mine_cells)
        self.assert_rejected("mine", Position(2, 2))
        self.assert_rejected("gun_tower", Position(0, 0))
        mine = self.game.build("mine", Position(1, 2))
        self.assertIsInstance(mine, Mine)

    def test_high_ground_bonus_requires_full_coverage(self) -> None:
        high_ground = frozenset(Footprint(3, 3).cells(Position(1, 2)))
        self.game.grid_map = replace(self.game.grid_map, high_ground_positions=high_ground)
        full = self.game.build("gun_tower", Position(1, 2))
        self.assertEqual(full.range, 9)
        self.game.demolish_tower(full.id)
        partial = self.game.build("gun_tower", Position(2, 2))
        self.assertEqual(partial.range, 6)

    def test_per_type_size_configuration_supports_rectangles(self) -> None:
        with patch.object(GunTower, "FOOTPRINT", Footprint(2, 4)):
            preview = self.game.preview_build("gun_tower", Position(1, 2))
            tower = self.game.build("gun_tower", Position(1, 2))
        cannon = self.game.build("cannon_tower", Position(4, 2))
        self.assertEqual((preview.width, preview.height), (2, 4))
        self.assertEqual(tower.center, WorldPosition(2, 4))
        self.assertEqual(tower.footprint, Footprint(2, 4))
        self.assertEqual(cannon.footprint, Footprint(3, 3))
        self.assert_rejected("power_node", Position(2, 5))

    def test_custom_core_reservation_matches_runtime_occupancy(self) -> None:
        game = GameState(replace(empty_map(), core_footprint=Footprint(2, 4)))
        core = game.building_at(Position(10, 10))
        self.assertEqual(core.footprint, Footprint(2, 4))
        for cell in core.occupied_cells():
            self.assertTrue(game.grid_map.is_core(cell))
            self.assertEqual(game.cell_snapshot(cell).terrain, "core")
            self.assertIs(game.building_at(cell), core)

    def test_preview_is_rechecked_and_failed_builds_never_consume_ids(self) -> None:
        self.assertTrue(self.game.preview_build("gun_tower", Position(1, 2)).is_valid)
        self.game.build("power_node", Position(3, 4))
        self.assert_rejected("gun_tower", Position(1, 2))
        self.game.gold = 0
        self.assert_rejected("gun_tower", Position(5, 2))
        for phase in (GamePhase.VICTORY, GamePhase.DEFEAT):
            self.game.phase = phase
            self.assert_rejected("gun_tower", Position(5, 2))
        before = self.game.snapshot()
        next_id = self.game.next_building_id
        for kind, position in (("unknown", Position(1, 2)), ([], Position(1, 2)),
                               ("gun_tower", None)):
            for operation in (self.game.preview_build, self.game.build):
                with self.assertRaises(ValueError):
                    operation(kind, position)
        self.assertEqual(self.game.snapshot(), before)
        self.assertEqual(self.game.next_building_id, next_id)


class FootprintPowerTest(unittest.TestCase):
    def test_radius_connection_counts_each_building_once(self) -> None:
        game = GameState(empty_map())
        node = game.build("power_node", Position(13, 12))
        # The tower has a gap from the node; coverage, rather than contact,
        # is what connects it.
        tower = game.build("gun_tower", Position(17, 12))
        report = game.latest_power_report
        self.assertTrue(tower.connected_to_grid)
        self.assertTrue(node.connected_to_grid)
        self.assertEqual(report.connected_count, 3)
        self.assertEqual(report.total_supply, 10)
        self.assertEqual(report.total_demand, 3)
        game.demolish_tower(tower.id)
        self.assertTrue(node.connected_to_grid)
        self.assertEqual(node.efficiency, 1.0)

    def test_radius_boundary_is_inclusive(self) -> None:
        # Six world units is the inclusive coverage boundary; seven is out.
        for anchor, expected in ((Position(13, 13), True), (Position(14, 13), False)):
            with self.subTest(anchor=anchor):
                game = GameState(empty_map())
                node = game.build("power_node", anchor)
                self.assertEqual(node.connected_to_grid, expected)
                self.assertEqual(game.latest_power_report.connected_count, 2 if expected else 1)

    def test_powered_consumers_cannot_relay_to_a_nearby_plant(self) -> None:
        game = GameState(empty_map())
        node = game.build("power_node", Position(13, 12))
        powered_tower = game.build("gun_tower", Position(17, 12))
        plant = game.build("power_plant", Position(17, 15))

        self.assertTrue(node.connected_to_grid)
        self.assertTrue(powered_tower.connected_to_grid)
        self.assertTrue(node.can_transmit_power())
        self.assertFalse(powered_tower.can_transmit_power())
        self.assertFalse(plant.connected_to_grid)
        self.assertEqual(plant.efficiency, 0.0)

    def test_mixed_sizes_and_input_order_do_not_change_connectivity(self) -> None:
        core = Core(1, Position(10, 10))
        with patch.object(PowerNode, "FOOTPRINT", Footprint(1, 2)):
            node = PowerNode(2, Position(13, 11))
        tower = GunTower(3, Position(14, 12))
        power = PowerGrid()
        forward = power.calculate(empty_map(), [core, node, tower])
        reverse = power.calculate(empty_map(), [tower, node, core])
        self.assertEqual(forward, reverse)
        self.assertEqual(reverse.connected_count, 3)
        self.assertEqual(reverse.total_demand, 3)


class ContinuousCombatTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game = GameState(create_demo_map())
        self.tower = self.game.build("gun_tower", Position(30, 6))

    def test_range_uses_centers_continuous_positions_and_inclusive_boundary(self) -> None:
        enemy = create_enemy("basic")
        self.game.enemies = [enemy]
        # Tower center=(31.5, 7.5), vertical road x=28.5. At progress 30
        # the enemy is (28.5, 10.5): exactly six world units away.
        enemy.path_progress = 30 - 0.01
        self.assertIsNone(self.game._select_target(self.tower))
        enemy.path_progress = 30
        self.assertIs(self.game._select_target(self.tower), enemy)
        enemy.path_progress = 30 + 0.01
        self.assertIs(self.game._select_target(self.tower), enemy)
        snapshot = self.game.snapshot()
        self.assertEqual(snapshot.cell_size, 1)
        self.assertEqual(snapshot.distance_metric, "manhattan")
        cell = self.game.cell_snapshot(enemy.position_on_route(self.game.grid_map.path))
        self.assertEqual(cell.enemies[0].world_position,
                         enemy.world_position_on_route(self.game.grid_map.path))
        self.assertEqual(cell.enemies[0].path_progress, enemy.path_progress)

    def test_metric_can_be_replaced_without_changing_route_geometry(self) -> None:
        enemy = create_enemy("basic")
        self.game.enemies = [enemy]
        length = self.game.grid_map.path.length
        with patch("grid_td.game_state.world_distance", return_value=0) as metric:
            self.assertIs(self.game._select_target(self.tower), enemy)
            metric.assert_called_once_with(self.tower.center,
                                           enemy.world_position_on_route(self.game.grid_map.path))
        self.assertEqual(self.game.grid_map.path.length, length)

    def test_equal_progress_breaks_ties_by_distance(self) -> None:
        far = Enemy("Far", max_hp=10, speed=0, damage_to_core=1, reward=0,
                    path_progress=30.0)
        near = Enemy("Near", max_hp=10, speed=0, damage_to_core=1, reward=0,
                     path_progress=30.0)
        self.game.enemies = [far, near]

        with patch.object(
            far, "world_position_on_route", return_value=WorldPosition(28.5, 10.5)
        ), patch.object(
            near, "world_position_on_route", return_value=WorldPosition(31.5, 7.5)
        ):
            self.assertIs(self.game._select_target(self.tower), near)

    def test_dead_targets_do_not_consume_another_towers_attack(self) -> None:
        second = self.game.build("gun_tower", Position(30, 9))
        first_enemy = Enemy("First", max_hp=1, speed=0, damage_to_core=1,
                            reward=4, path_progress=30)
        next_enemy = Enemy("Next", max_hp=1, speed=0, damage_to_core=1,
                           reward=5, path_progress=30)
        self.game.enemies = [first_enemy, next_enemy]
        before = self.game.gold
        self.game._towers_attack(0)
        self.assertEqual(self.game.enemies, [])
        self.assertEqual(self.game.gold, before + 9)
        self.assertGreater(self.tower.cooldown_remaining, 0)
        self.assertGreater(second.cooldown_remaining, 0)
        self.game._towers_attack(0)
        self.assertEqual(self.game.gold, before + 9)


if __name__ == "__main__":
    unittest.main()
