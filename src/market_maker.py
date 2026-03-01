import numpy as np
from dataclasses import dataclass
from orderBook import OrderBook, Side

@dataclass
class MarketMakerConfig:
    base_spread:    float = 0.10  # total spread to capture (split evenly each side)
    quote_size:     float = 5.0   # shares per quote
    inventory_skew: float = 0.01  # price shift per unit of net inventory
    max_inventory:  float = 50.0  # hard limit — stop quoting one side if breached
    requote_every:  int   = 1     # re-quote every N simulation steps

@dataclass
class MMSnapshot:
    step:           int
    mid_price:      float
    bid_quote:      float
    ask_quote:      float
    inventory:      float
    cash:           float
    realized_pnl:   float
    unrealized_pnl: float
    total_pnl:      float

class MarketMaker:
    def __init__(self, book: OrderBook, config: MarketMakerConfig | None = None):
        self.book   = book
        self.config = config or MarketMakerConfig()

        # P&L state
        self.inventory:    float = 0.0
        self.cash:         float = 0.0

        # Active quote order ids
        self._bid_order_id: int | None = None
        self._ask_order_id: int | None = None

        # All MM order ids
        self._mm_order_ids: set[int] = set()

        # Side each MM order was placed on  {order_id: Side}
        self._order_side: dict[int, Side] = {}

        # Fill ids already processed
        self._accounted_fills: set[int] = set()

        # History
        self.snapshots:   list[MMSnapshot] = []
        self._step_count: int = 0

    # ── Public API ─────────────────────────────

    def step(self, mark_price: float | None = None):
        self._step_count += 1
        self._process_fills()

        if self._step_count % self.config.requote_every == 0:
            self._cancel_quotes()
            self._post_quotes()

        self._record_snapshot(mark_price)

    def print_summary(self):
        if not self.snapshots:
            print("No snapshots recorded.")
            return

        final    = self.snapshots[-1]
        peak_inv = max(abs(s.inventory) for s in self.snapshots)
        pnl_list = [s.total_pnl for s in self.snapshots]

        mm_fills = [
            f for f in self.book.fills
            if f.maker_order_id in self._mm_order_ids
            or f.taker_order_id in self._mm_order_ids
        ]

        print("── Market Maker Summary ────────────────────")
        print(f"  Steps run          : {self._step_count}")
        print(f"  Final inventory    : {final.inventory:.2f}")
        print(f"  Peak |inventory|   : {peak_inv:.2f}")
        print(f"  Cash               : {final.cash:.4f}")
        print(f"  Realized P&L       : {final.realized_pnl:.4f}")
        print(f"  Unrealized P&L     : {final.unrealized_pnl:.4f}")
        print(f"  Total P&L          : {final.total_pnl:.4f}")
        print(f"  Max drawdown       : {self._max_drawdown(pnl_list):.4f}")
        print(f"  MM fills           : {len(mm_fills)}")
        print(f"  MM fill volume     : {sum(f.quantity for f in mm_fills):.2f}")
        if len(self.snapshots) > 1:
            print(f"  Sharpe (step P&L)  : {self._sharpe():.4f}")

    def snapshots_to_df(self):
        import pandas as pd
        return pd.DataFrame([s.__dict__ for s in self.snapshots])

    # ── Quoting ────────────────────────────────

    def _post_quotes(self):
        cfg = self.config
        mid = self.book.mid_price()
        if mid is None:
            return

        half_spread = cfg.base_spread / 2
        skew        = self.inventory * cfg.inventory_skew

        bid_price = round(mid - half_spread - skew, 4)
        ask_price = round(mid + half_spread - skew, 4)

        # Guarantee ask > bid after skewing
        if ask_price <= bid_price:
            ask_price = round(bid_price + 0.0001, 4)

        post_bid = self.inventory <  cfg.max_inventory
        post_ask = self.inventory > -cfg.max_inventory

        if post_bid and bid_price > 0:
            oid, _ = self.book.add_limit_order(Side.BID, bid_price, cfg.quote_size)
            self._bid_order_id    = oid
            self._mm_order_ids.add(oid)
            self._order_side[oid] = Side.BID

        if post_ask:
            oid, _ = self.book.add_limit_order(Side.ASK, ask_price, cfg.quote_size)
            self._ask_order_id    = oid
            self._mm_order_ids.add(oid)
            self._order_side[oid] = Side.ASK

    def _cancel_quotes(self):
        for oid in (self._bid_order_id, self._ask_order_id):
            if oid is not None:
                self.book.cancel_order(oid)
        self._bid_order_id = None
        self._ask_order_id = None

    # ── Fill processing ────────────────────────

    def _process_fills(self):
        for fill in self.book.fills:
            if fill.fill_id in self._accounted_fills:
                continue

            is_maker = fill.maker_order_id in self._mm_order_ids
            is_taker = fill.taker_order_id in self._mm_order_ids

            if not is_maker and not is_taker:
                continue

            mm_order_id = fill.maker_order_id if is_maker else fill.taker_order_id
            side = self._order_side.get(mm_order_id)
            if side is None:
                continue

            qty = fill.quantity

            if side == Side.BID:
                self.cash      -= fill.price * qty
                self.inventory += qty
            else:
                self.cash      += fill.price * qty
                self.inventory -= qty

            self._accounted_fills.add(fill.fill_id)

    # ── Snapshot ───────────────────────────────

    def _record_snapshot(self, mark_price: float | None = None):
        mid  = mark_price if mark_price is not None else (self.book.mid_price() or 0.0)
        unrl = self.inventory * mid

        def _quote_price(oid):
            if oid is not None and oid in self.book.orders:
                return self.book.orders[oid].price
            return float("nan")

        self.snapshots.append(MMSnapshot(
            step           = self._step_count,
            mid_price      = mid,
            bid_quote      = _quote_price(self._bid_order_id),
            ask_quote      = _quote_price(self._ask_order_id),
            inventory      = self.inventory,
            cash           = self.cash,
            realized_pnl   = self.cash,
            unrealized_pnl = unrl,
            total_pnl      = self.cash + unrl,
        ))

    # ── Analytics ──────────────────────────────

    @staticmethod
    def _max_drawdown(pnl_series: list[float]) -> float:
        peak   = float("-inf")
        max_dd = 0.0
        for v in pnl_series:
            peak   = max(peak, v)
            max_dd = max(max_dd, peak - v)
        return max_dd

    def _sharpe(self) -> float:
        pnls    = np.array([s.total_pnl for s in self.snapshots])
        returns = np.diff(pnls)
        std     = returns.std()
        if std == 0:
            return 0.0
        return float(returns.mean() / std * np.sqrt(len(returns)))


# ─────────────────────────────────────────────
#  Smoke test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    from order_flow_simulator import OrderFlowSimulator, SimulatorConfig

    book = OrderBook("AAPL")
    sim  = OrderFlowSimulator(book, SimulatorConfig(
        initial_price      = 100.0,
        price_vol          = 0.02,
        limit_arrive_prob  = 0.70,
        market_arrive_prob = 0.25,
        cancel_prob        = 0.15,
        seed               = 43,
        informed_fraction  = 1.0
    ))
    mm = MarketMaker(book, MarketMakerConfig(
        base_spread    = 0.15,
        quote_size     = 5.0,
        inventory_skew = 0.01,
        max_inventory  = 10.0,
    ))

    N = 10000
    for _ in range(N):
        sim.step()
        mm.step(mark_price=sim.true_price)

    print(book)
    print()
    mm.print_summary()

    # print()
    # print("── P&L Curve (every 200 steps) ─────────────")
    # for snap in mm.snapshots[::200]:
    #     bar    = "█" * max(0, int(snap.total_pnl / 0.5))
    #     prefix = " " if snap.total_pnl >= 0 else "-"
    #     print(
    #         f"  step {snap.step:>5}  "
    #         f"inv={snap.inventory:>7.2f}  "
    #         f"total_pnl={snap.total_pnl:>8.4f}  "
    #         f"{prefix}{bar}"
    #     )

    import matplotlib.pyplot as plt
    plt.plot([snap.total_pnl for snap in mm.snapshots])
    plt.show()