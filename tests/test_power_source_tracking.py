"""Coverage for direct power-source tracking in the core snapshot contract."""

import unittest

from grid_td.game_state import GameState
from grid_td.map import GridMap
from grid_td.position import Position


def make_map() -> GridMap:
    return GridMap(
        width=24,
        height=12,
        route=(Position(0, 0),),
        core_position=Position(0, 0),
        mine_positions=frozenset(),
        high_ground_positions=frozenset(),
        illegal_ground_positions=frozenset(),
    )


class PowerSourceTrackingTest(unittest.TestCase):
    def test_transmitter_chain_records_direct_upstream_sources(self) -> None:
        game = GameState(make_map(), gold=1000)
        node_a = game.build("power_node", Position(3, 0))
        node_b = game.build("power_node", Position(6, 0))
        tower = game.build("gun_tower", Position(9, 0))
        core = game.building_at(game.grid_map.core_position)
        assert core is not None

        self.assertIsNone(core.power_source_id)
        self.assertEqual(node_a.power_source_id, core.id)
        self.assertEqual(node_b.power_source_id, node_a.id)
        self.assertEqual(tower.power_source_id, node_b.id)

    def test_consumer_uses_best_quality_source_and_snapshot_exposes_it(self) -> None:
        game = GameState(make_map(), gold=1000)
        plant = game.build("power_plant", Position(3, 3))
        tower = game.build("gun_tower", Position(6, 3))

        self.assertEqual(tower.power_source_id, plant.id)
        snapshot = game.cell_snapshot(tower.position).building
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.power_source_id, plant.id)

    def test_disconnected_building_has_no_power_source(self) -> None:
        game = GameState(make_map(), gold=1000)
        tower = game.build("gun_tower", Position(18, 9))

        self.assertFalse(tower.connected_to_grid)
        self.assertIsNone(tower.power_source_id)
        snapshot = game.cell_snapshot(tower.position).building
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertIsNone(snapshot.power_source_id)

    def test_source_updates_after_node_destruction(self) -> None:
        game = GameState(make_map(), gold=1000)
        node = game.build("power_node", Position(3, 0))
        tower = game.build("gun_tower", Position(9, 0))
        self.assertEqual(tower.power_source_id, node.id)

        node.take_damage(node.hp)
        game.recalculate_power()

        self.assertIsNone(tower.power_source_id)
        self.assertFalse(tower.connected_to_grid)


if __name__ == "__main__":
    unittest.main()
