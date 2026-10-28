"""Coverage for damaged power-node transmission quality."""

import unittest

from grid_td.game_state import GameState
from grid_td.map import GridMap
from grid_td.position import Position


def make_map(width: int, height: int) -> GridMap:
    """Build a simple map with the core at the top-left."""
    return GridMap(
        width=width,
        height=height,
        route=(Position(0, 0),),
        core_position=Position(0, 0),
        mine_positions=frozenset(),
        high_ground_positions=frozenset(),
        illegal_ground_positions=frozenset(),
    )


class NodeTransmissionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game = GameState(make_map(24, 12), gold=1000)
        self.node_a = self.game.build("power_node", Position(6, 0))
        self.node_b = self.game.build("power_node", Position(12, 0))
        self.tower = self.game.build("gun_tower", Position(18, 0))

    def test_damaged_node_reduces_downstream_transmission(self) -> None:
        self.assertEqual(self.tower.transmission_efficiency, 1.0)
        self.assertEqual(self.tower.efficiency, 1.0)

        self.node_a.take_damage(3)
        self.game.recalculate_power()

        self.assertAlmostEqual(self.node_a.health_efficiency, 0.6)
        self.assertAlmostEqual(self.node_b.transmission_efficiency, 0.6)
        self.assertAlmostEqual(self.tower.transmission_efficiency, 0.6)
        self.assertAlmostEqual(self.tower.efficiency, 0.6)
        self.assertEqual(self.game.latest_power_report.efficiency, 1.0)

    def test_chained_node_damage_multiplies(self) -> None:
        self.node_a.take_damage(3)
        self.node_b.take_damage(3)
        self.game.recalculate_power()

        self.assertAlmostEqual(self.tower.transmission_efficiency, 0.36)
        self.assertAlmostEqual(self.tower.efficiency, 0.36)

    def test_repair_restores_transmission(self) -> None:
        self.node_a.take_damage(3)
        self.game.recalculate_power()
        self.assertAlmostEqual(self.tower.transmission_efficiency, 0.6)

        self.game.repair_building(self.node_a.id)

        self.assertAlmostEqual(self.tower.transmission_efficiency, 1.0)
        self.assertAlmostEqual(self.tower.efficiency, 1.0)

    def test_snapshot_exposes_transmission_efficiency(self) -> None:
        self.node_a.take_damage(3)
        self.game.recalculate_power()

        building = self.game.cell_snapshot(Position(18, 0)).building

        self.assertIsNotNone(building)
        assert building is not None
        self.assertAlmostEqual(building.transmission_efficiency, 0.6)
        self.assertAlmostEqual(building.efficiency, 0.6)

    def test_healthy_power_source_wins_over_damaged_node(self) -> None:
        game = GameState(make_map(12, 12), gold=1000)
        game.build("power_plant", Position(0, 6))
        node = game.build("power_node", Position(6, 0))
        tower = game.build("gun_tower", Position(6, 6))
        node.take_damage(3)
        game.recalculate_power()

        self.assertAlmostEqual(node.transmission_efficiency, 0.6)
        self.assertAlmostEqual(tower.transmission_efficiency, 1.0)
        self.assertAlmostEqual(tower.efficiency, 1.0)

    def test_core_and_plant_transmission_are_clean(self) -> None:
        game = GameState(make_map(12, 12), gold=1000)
        plant = game.build("power_plant", Position(0, 6))
        game.recalculate_power()
        core = game.building_at(game.grid_map.core_position)

        self.assertIsNotNone(core)
        self.assertEqual(core.transmission_efficiency, 1.0)
        self.assertEqual(plant.transmission_efficiency, 1.0)


if __name__ == "__main__":
    unittest.main()
