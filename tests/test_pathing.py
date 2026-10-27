"""Pathfinding baselines for open ground, building nodes and breach choices."""

import unittest

from grid_td.buildings import Building, GunTower
from grid_td.map import GridMap
from grid_td.pathing import find_path
from grid_td.position import Position


def make_map(
    width: int,
    height: int,
    core_position: Position,
    *,
    illegal: frozenset[Position] = frozenset(),
    walk_only: frozenset[Position] = frozenset(),
    build_only: frozenset[Position] = frozenset(),
) -> GridMap:
    """Build a minimal map independent of the demo terrain."""
    return GridMap(
        width=width,
        height=height,
        route=(Position(0, 0),),
        core_position=core_position,
        mine_positions=frozenset(),
        high_ground_positions=frozenset(),
        illegal_ground_positions=illegal,
        walk_only_positions=walk_only,
        build_only_positions=build_only,
    )


class TerrainCapabilityTest(unittest.TestCase):
    def test_walk_only_and_build_only_are_separate_capabilities(self) -> None:
        grid_map = make_map(
            8,
            8,
            Position(5, 5),
            walk_only=frozenset({Position(1, 1)}),
            build_only=frozenset({Position(2, 2)}),
        )

        self.assertTrue(grid_map.is_walkable(Position(1, 1)))
        self.assertFalse(grid_map.is_buildable_terrain(Position(1, 1)))
        self.assertFalse(grid_map.is_walkable(Position(2, 2)))
        self.assertTrue(grid_map.is_buildable_terrain(Position(2, 2)))
        self.assertTrue(grid_map.is_walkable(Position(3, 3)))
        self.assertTrue(grid_map.is_buildable_terrain(Position(3, 3)))

    def test_overlapping_capability_cells_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            make_map(
                8,
                8,
                Position(5, 5),
                walk_only=frozenset({Position(1, 1)}),
                build_only=frozenset({Position(1, 1)}),
            )


class OpenGroundPathingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.grid_map = make_map(15, 12, Position(12, 6))
        self.start = Position(0, 0)

    def test_normal_path_avoids_a_single_building(self) -> None:
        building = GunTower(1, Position(5, 4))

        plan = find_path(
            self.grid_map,
            [building],
            self.start,
            enemy_speed=2.25,
            breach_damage=1.0,
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertFalse(plan.used_breach)
        self.assertIsNone(plan.breach_target_id)
        self.assertIsNotNone(plan.normal_time)
        self.assertGreater(plan.route.length, 0)

    def test_straight_route_is_compressed(self) -> None:
        grid_map = make_map(12, 6, Position(9, 0))
        plan = find_path(
            grid_map,
            [],
            Position(0, 0),
            enemy_speed=1.0,
            breach_damage=1.0,
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertLessEqual(len(plan.route.points), 2)

    def test_invalid_arguments_are_rejected(self) -> None:
        for speed, damage, ratio in (
            (0, 1, 1.5),
            (-1, 1, 1.5),
            (1, 0, 1.5),
            (1, 1, 0),
            (True, 1, 1.5),
        ):
            with self.subTest(speed=speed, damage=damage, ratio=ratio):
                with self.assertRaises(ValueError):
                    find_path(
                        self.grid_map,
                        [],
                        self.start,
                        enemy_speed=speed,
                        breach_damage=damage,
                        breach_time_ratio=ratio,
                    )

    def test_unwalkable_start_is_rejected(self) -> None:
        build_only = make_map(
            8,
            8,
            Position(5, 5),
            build_only=frozenset({Position(0, 0)}),
        )
        with self.assertRaises(ValueError):
            find_path(
                build_only,
                [],
                Position(0, 0),
                enemy_speed=1.0,
                breach_damage=1.0,
            )


class BreachPathingTest(unittest.TestCase):
    def test_fully_blocked_wall_uses_first_building(self) -> None:
        grid_map = make_map(12, 12, Position(9, 7))
        buildings = [
            GunTower(1, Position(3, 0)),
            GunTower(2, Position(3, 3)),
            GunTower(3, Position(3, 6)),
            GunTower(4, Position(3, 9)),
        ]

        plan = find_path(
            grid_map,
            buildings,
            Position(0, 0),
            enemy_speed=2.25,
            breach_damage=1.0,
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertTrue(plan.used_breach)
        self.assertIsNone(plan.normal_time)
        self.assertIn(plan.breach_target_id, {1, 2, 3, 4})
        self.assertGreater(plan.route.length, 0)

    def test_weak_wall_is_breached_despite_a_detour(self) -> None:
        illegal = frozenset(
            Position(6, y) for y in list(range(0, 9)) + list(range(12, 19))
        )
        grid_map = make_map(20, 20, Position(17, 10), illegal=illegal)
        buildings = [
            Building(1, "Weak", Position(6, 9), cost=0, max_hp=2),
        ]

        plan = find_path(
            grid_map,
            buildings,
            Position(0, 10),
            enemy_speed=2.25,
            breach_damage=1.0,
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertTrue(plan.used_breach)
        self.assertEqual(plan.breach_target_id, 1)
        self.assertIsNotNone(plan.normal_time)
        self.assertGreater(plan.normal_time, plan.breach_time * 1.5)

    def test_destroyed_building_no_longer_blocks(self) -> None:
        grid_map = make_map(12, 12, Position(9, 7))
        buildings = [
            GunTower(1, Position(3, 0)),
            GunTower(2, Position(3, 3)),
            GunTower(3, Position(3, 6)),
            GunTower(4, Position(3, 9)),
        ]
        buildings[1].take_damage(buildings[1].hp)

        plan = find_path(
            grid_map,
            buildings,
            Position(0, 0),
            enemy_speed=2.25,
            breach_damage=1.0,
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertFalse(plan.used_breach)
        self.assertIsNotNone(plan.normal_time)

    def test_breach_damage_changes_breach_time(self) -> None:
        grid_map = make_map(12, 12, Position(9, 7))
        buildings = [
            GunTower(1, Position(3, 0)),
            GunTower(2, Position(3, 3)),
            GunTower(3, Position(3, 6)),
            GunTower(4, Position(3, 9)),
        ]
        weak = find_path(
            grid_map,
            buildings,
            Position(0, 0),
            enemy_speed=2.25,
            breach_damage=2.0,
        )
        strong = find_path(
            grid_map,
            buildings,
            Position(0, 0),
            enemy_speed=2.25,
            breach_damage=0.5,
        )

        self.assertIsNotNone(weak)
        self.assertIsNotNone(strong)
        assert weak is not None and strong is not None
        self.assertLess(weak.breach_time, strong.breach_time)


if __name__ == "__main__":
    unittest.main()
