# Order Book Simulator
A limit order book simulation that models price impact, bid-ask spread dynamics, and queue priority. Includes a synthetic order flow engine and an inventory-skewing market making strategy with full P&L tracking.

---

## Overview
This project simulates the core mechanics of how financial exchanges work at the microstructure level. It is built in five layers, each depending on the one below it:

```
MarketMaker.ipynb      ← testing layer: used for testing and param sweeping
market_maker.py        ← strategy layer: quotes, inventory, P&L
event_log.py           ← analytics layer: DataFrames, VWAP, volume profile
order_flow_simulator.py ← flow layer: Poisson arrivals, informed traders
orderBook.py           ← core layer: matching engine, order management
```

---

## Installation

```bash
git clone https://github.com/KyleC144/OrderBookSim.git
cd OrderBookSim
pip install -r requirements.txt
```

---

## Quick Start

```python
from orderBook import OrderBook
from order_flow_simulator import OrderFlowSimulator, SimulatorConfig
from market_maker import MarketMaker, MarketMakerConfig

book = OrderBook("AAPL")
sim  = OrderFlowSimulator(book, SimulatorConfig(seed=42))
mm   = MarketMaker(book, MarketMakerConfig())

for _ in range(2000):
    sim.step()
    mm.step(mark_price=sim.true_price)

mm.print_summary()
```

Each file can also be run directly:

```bash
python orderBook.py
python order_flow_simulator.py
python event_log.py
python market_maker.py
```

---

## File Reference

### `orderBook.py`

The core matching engine. Implements a price-time priority limit order book using two `SortedDict`s, bids keyed by negative price, asks keyed by positive price, so the best quote is always at index 0. Each price level holds a `deque` of orders preserving arrival order (FIFO queue priority).

**Key classes:**

`Order` - a single order with id, side, type, price, quantity, fill state, and status.

`Fill` - a matched trade record with maker/taker order ids, price, and quantity.

`Event` - a log entry for every book action (placement, fill, cancel) with a mid price and spread snapshot at the time of the event.

`OrderBook` - the main class. Exposes:

```python
book.add_limit_order(side, price, quantity)  # returns (order_id, fills)
book.add_market_order(side, quantity)        # returns (order_id, fills)
book.cancel_order(order_id)                  # returns bool
book.best_bid()                              # float | None
book.best_ask()                              # float | None
book.mid_price()                             # float | None
book.spread()                                # float | None
book.depth(levels=5)                         # dict of bids/asks
book.fills                                   # list[Fill]
book.events                                  # list[Event]
```

---

### `order_flow_simulator.py`

Drives the order book with synthetic order flow modelled as a Poisson process. Each step three independent Bernoulli draws occur: does a limit order arrive? Does a market order arrive? Does a random cancel occur?

**Informed traders:** A configurable fraction of market orders are placed by "informed" traders who know the direction of the next price move before it occurs. Orders are placed against stale quotes *before* the true price updates, giving informed traders a genuine edge. This models adverse selection, the damage informed flow causes depends critically on whether the price signal has momentum across steps.

**Key class: `SimulatorConfig`**

| Parameter | Default | Description |
|---|---|---|
| `initial_price` | 100.0 | Starting true price |
| `price_vol` | 0.02 | Std dev of per-step price move |
| `limit_arrive_prob` | 0.70 | Probability a limit order arrives each step |
| `market_arrive_prob` | 0.20 | Probability a market order arrives each step |
| `cancel_prob` | 0.15 | Probability a random cancel occurs each step |
| `offset_scale` | 0.05 | Exponential scale for limit order placement offset from true price |
| `informed_fraction` | 0.10 | Fraction of market orders that are informed |
| `seed` | 42 | RNG seed for reproducibility |

**Key class: `OrderFlowSimulator`**

```python
sim = OrderFlowSimulator(book, config)
sim.step()                    # advance one step
sim.run(n_steps)              # advance n steps
sim.true_price                # current fundamental price
sim.true_price_history        # list of true prices per step
sim.mid_price_history         # list of book mid prices per step
sim.spread_history            # list of spreads per step
sim.summary()                 # dict of summary statistics
```

---

### `event_log.py`

Analytics utilities that convert the raw order book logs into pandas DataFrames for analysis and plotting.

```python
from event_log import fills_to_df, events_to_df, volume_profile, print_summary

fills_df  = fills_to_df(book)     # DataFrame of all trades
events_df = events_to_df(book)    # DataFrame of all book events
vp        = volume_profile(book)  # volume traded per price bin
print_summary(book)               # human-readable stats to stdout
```

`fills_to_df` columns: `fill_id`, `maker_order_id`, `taker_order_id`, `price`, `quantity`, `timestamp`

`events_to_df` columns: `event_id`, `event_type`, `order_id`, `side`, `price`, `quantity`, `fill_id`, `mid_price`, `spread`, `timestamp`

---

### `market_maker.py`

An inventory-skewing market maker. Each step it cancels its resting quotes, computes a new bid and ask around mid price with an inventory-based skew, and posts fresh limit orders on both sides.

**Skewing logic:** If the MM is long, both quotes shift downward, the bid becomes less aggressive (avoiding more inventory accumulation) and the ask becomes cheaper (encouraging sells to reduce exposure). The skew magnitude is `inventory × inventory_skew`.

**P&L accounting:**
- `cash` - running sum of all cash flows from fills
- `unrealized_pnl` - inventory marked to `mark_price` (should be `sim.true_price`, not book mid)
- `total_pnl` - cash + unrealized

**Important:** always pass `mark_price=sim.true_price` to `mm.step()`. Marking to book mid underestimates inventory losses from adverse selection because the book mid does not reliably track the true price step-by-step.

**Key class: `MarketMakerConfig`**

| Parameter | Default | Description |
|---|---|---|
| `base_spread` | 0.10 | Total spread to capture, split evenly each side |
| `quote_size` | 5.0 | Shares per quote |
| `inventory_skew` | 0.01 | Price adjustment per unit of net inventory |
| `max_inventory` | 50.0 | Hard limit, stops quoting one side if breached |
| `requote_every` | 1 | Re-quote every N steps |

**Key class: `MarketMaker`**

```python
mm = MarketMaker(book, config)
mm.step(mark_price=sim.true_price)  # advance one step
mm.print_summary()                  # print P&L and risk stats
mm.snapshots_to_df()                # DataFrame of per-step snapshots
mm.snapshots                        # list[MMSnapshot]
```

`MMSnapshot` fields: `step`, `mid_price`, `bid_quote`, `ask_quote`, `inventory`, `cash`, `realized_pnl`, `unrealized_pnl`, `total_pnl`

---

## Key Concepts

**Why market making is profitable:** The MM captures the bid-ask spread on every filled trade. As long as uninformed flow exceeds informed flow, this spread capture outweighs inventory losses from adverse selection.

**Adverse selection:** Informed traders know which direction the price will move and trade against the MM's stale quotes before the book reprices. Each informed fill leaves the MM with inventory that is immediately worth less than the fill price.

**Why `informed_fraction = 1.0` is still profitable:** When informed traders have a single-step signal with no momentum, their trades are symmetric over time, half buys, half sells. Inventory mean-reverts naturally and spread capture accumulates without a persistent directional loss. Momentum is what truly kills a market maker, because it causes inventory to compound in one direction faster than spread capture can offset it.

**Inventory skewing vs spread widening:** Two competing responses to inventory risk. Skewing keeps fill rate high but accepts more adverse fills. Widening reduces adverse selection but also reduces fill rate. The optimal choice depends on the informed fraction and signal persistence of the incoming flow.

---

## Extensions in Progress
- **Momentum in informed flow** - give informed traders a multi-step signal so adverse selection compounds; this is what makes `informed_fraction = 1.0` genuinely unprofitable
- **Flow toxicity detection** - have the MM estimate order flow imbalance in real time and widen spreads dynamically when it detects momentum
- **Multiple market makers** - introduce competition and observe how spreads tighten
- **Realistic tick sizes** - constrain prices to discrete ticks and observe queue dynamics

---

## References
- Glosten & Milgrom (1985) - *Bid, Ask and Transaction Prices in a Specialist Market with Heterogeneously Informed Traders* - the theoretical foundation for adverse selection in market making
- Avellaneda & Stoikov (2008) - *High-frequency trading in a limit order book* - the canonical inventory-skewing market maker model that this implementation is based on
- Harris (2003) - *Trading and Exchanges* - accessible overview of market microstructure