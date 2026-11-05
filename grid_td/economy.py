"""Wave-settlement economy calculations.

``GameState.end_wave()`` applies the returned values and handles phase
transitions. Keeping the arithmetic here makes the economy rules easy to test
without constructing a full game.
"""

from __future__ import annotations

from dataclasses import dataclass

from grid_td.buildings import Building, Mine

INTEREST_RATE = 0.12
REPAIR_SERVICE_FEE = 5


@dataclass(frozen=True)
class Settlement:
    """One wave's income and costs before applying them to gold."""

    mine_income: int
    interest: int
    repair_cost: int

    @property
    def net_gold(self) -> int:
        """Return the gold change before applying the settlement."""
        return self.mine_income - self.interest - self.repair_cost


def calculate_settlement(buildings: list[Building], debt: int) -> Settlement:
    """Calculate mine income, debt interest, and overload service fees."""
    mine_income = sum(
        building.collect_income()
        for building in buildings
        if isinstance(building, Mine)
    )
    interest = round(debt * INTEREST_RATE)
    repair_cost = sum(
        REPAIR_SERVICE_FEE for building in buildings if building.needs_repair
    )
    return Settlement(
        mine_income=mine_income,
        interest=interest,
        repair_cost=repair_cost,
    )


def format_settlement(settlement: Settlement, gold_after: int) -> str:
    """Return the player-facing settlement summary."""
    return (
        f"Wave ended. Mine income +{settlement.mine_income}, "
        f"interest -{settlement.interest}, repairs -{settlement.repair_cost}, "
        f"gold {gold_after}."
    )
