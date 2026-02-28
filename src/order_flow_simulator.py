"""
order_flow_simulator.py
────────────────────────
Drives the OrderBook with synthetic order flow modelled as a Poisson process.

Arrival rates and price dynamics are configurable. The true (fundamental) price
follows a discrete random walk; limit orders are placed around it with
exponentially-distributed offsets, and market orders arrive at a lower rate.
A random fraction of resting orders are cancelled each step.
"""

import numpy as np
from dataclasses import dataclass, field

from orderBook import OrderBook, Side


# ─────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────

@dataclass
class SimulatorConfig:
    # Price dynamics
    initial_price: float  = 100.0   # starting true price
    price_vol:     float  = 0.02    # std dev of per-step price move

    # Arrival probabilities per step  (independent Bernoulli draws)
    limit_arrive_prob:  float = 0.70  # probability a limit order arrives
    market_arrive_prob: float = 0.20  # probability a market order arrives
    cancel_prob:        float = 0.15  # probability a random cancel occurs

    # Order sizing
    limit_qty_min:  int   = 1
    limit_qty_max:  int   = 10
    market_qty_min: int   = 1
    market_qty_max: int   = 5

    # Spread / quote placement
    # Limit orders are placed at true_price ± Exp(offset_scale) from mid
    offset_scale: float = 0.05

    # Fraction of informed traders (they trade in the direction of the move)
    informed_fraction: float = 0.10

    seed: int = 42


# ─────────────────────────────────────────────
#  Simulator
# ─────────────────────────────────────────────

class OrderFlowSimulator:
    """
    Injects synthetic order flow into an OrderBook.

    Parameters
    ----------
    book   : OrderBook  — the book to drive
    config : SimulatorConfig  — arrival rate / price parameters
    """

    def __init__(self, book: OrderBook, config: SimulatorConfig | None = None):
        self.book   = book
        self.config = config or SimulatorConfig()
        self.rng    = np.random.default_rng(self.config.seed)

        self._true_price: float      = self.config.initial_price
        self._resting_ids: list[int] = []   # pool of cancellable order ids

        # Time series snapshots (appended each step)
        self.true_price_history: list[float]        = []
        self.mid_price_history:  list[float | None] = []
        self.spread_history:     list[float | None] = []

    @property
    def true_price(self) -> float:
        return self._true_price

    # ── Core simulation step ───────────────────

    def step(self):
        """Advance the simulation by one time step."""
        cfg = self.config
        rng = self.rng

        # 1. Evolve true price (random walk)
        self._true_price += rng.normal(0, cfg.price_vol)

        # 2. Limit order arrival
        if rng.random() < cfg.limit_arrive_prob:
            self._place_limit_order()

        # 3. Market order arrival
        if rng.random() < cfg.market_arrive_prob:
            self._place_market_order()

        # 4. Random cancellation
        if rng.random() < cfg.cancel_prob and self._resting_ids:
            self._cancel_random()

        # 5. Snapshot
        self.true_price_history.append(self._true_price)
        self.mid_price_history.append(self.book.mid_price())
        self.spread_history.append(self.book.spread())

    def run(self, n_steps: int):
        """Run the simulator for n_steps steps."""
        for _ in range(n_steps):
            self.step()

    # ── Private helpers ────────────────────────

    def _place_limit_order(self):
        cfg = self.config
        rng = self.rng

        side   = Side.BID if rng.random() < 0.5 else Side.ASK
        offset = rng.exponential(cfg.offset_scale)
        price  = round(
            self._true_price - offset if side == Side.BID
            else self._true_price + offset,
            4,
        )
        qty = int(rng.integers(cfg.limit_qty_min, cfg.limit_qty_max + 1))

        oid, _ = self.book.add_limit_order(side, price, qty)

        # Track resting orders for possible future cancellation
        if oid in self.book.orders:
            self._resting_ids.append(oid)

    def _place_market_order(self):
        cfg = self.config
        rng = self.rng

        # Informed traders trade in direction of next price move
        if rng.random() < cfg.informed_fraction:
            # peek at "true" direction: if price drifted up, buy; else sell
            drift = rng.normal(0, cfg.price_vol)
            side  = Side.BID if drift > 0 else Side.ASK
        else:
            side = Side.BID if rng.random() < 0.5 else Side.ASK

        qty = int(rng.integers(cfg.market_qty_min, cfg.market_qty_max + 1))
        self.book.add_market_order(side, qty)

    def _cancel_random(self):
        idx    = self.rng.integers(len(self._resting_ids))
        oid    = self._resting_ids.pop(idx)
        self.book.cancel_order(oid)

    # ── Summary ────────────────────────────────

    def summary(self) -> dict:
        valid_mids    = [m for m in self.mid_price_history if m is not None]
        valid_spreads = [s for s in self.spread_history    if s is not None]
        return {
            "steps":          len(self.true_price_history),
            "true_price_start": self.true_price_history[0]  if self.true_price_history else None,
            "true_price_end":   self.true_price_history[-1] if self.true_price_history else None,
            "mid_price_mean":   float(np.mean(valid_mids))    if valid_mids    else None,
            "spread_mean":      float(np.mean(valid_spreads)) if valid_spreads else None,
            "spread_min":       float(np.min(valid_spreads))  if valid_spreads else None,
            "spread_max":       float(np.max(valid_spreads))  if valid_spreads else None,
            "total_fills":      len(self.book.fills),
            "total_events":     len(self.book.events),
        }


# ─────────────────────────────────────────────
#  Smoke test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    book = OrderBook("AAPL")
    cfg  = SimulatorConfig(initial_price=100.0, seed=42)
    sim  = OrderFlowSimulator(book, cfg)

    sim.run(500)

    print(book)
    print()

    s = sim.summary()
    print("── Simulation Summary ──────────────────")
    for k, v in s.items():
        print(f"  {k:<25} {v}")

    print()
    print(f"Last 5 fills:")
    for fill in book.fills[-5:]:
        print(" ", fill)

    print()
    print(f"Last 5 events:")
    for event in book.events[-5:]:
        print(" ", event)