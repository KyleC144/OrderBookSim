import pandas as pd
from orderBook import OrderBook


# ─────────────────────────────────────────────
#  DataFrame builders
# ─────────────────────────────────────────────

def fills_to_df(book: OrderBook) -> pd.DataFrame:
    """Convert book.fills to a DataFrame."""
    if not book.fills:
        return pd.DataFrame()
    records = [
        {
            "fill_id":        f.fill_id,
            "maker_order_id": f.maker_order_id,
            "taker_order_id": f.taker_order_id,
            "price":          f.price,
            "quantity":       f.quantity,
            "timestamp":      f.timestamp,
        }
        for f in book.fills
    ]
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
    return df


def events_to_df(book: OrderBook) -> pd.DataFrame:
    """Convert book.events to a DataFrame."""
    if not book.events:
        return pd.DataFrame()
    records = [
        {
            "event_id":   e.event_id,
            "event_type": e.event_type.value,
            "order_id":   e.order_id,
            "side":       e.side.value if e.side else None,
            "price":      e.price,
            "quantity":   e.quantity,
            "fill_id":    e.fill_id,
            "mid_price":  e.mid_price,
            "spread":     e.spread,
            "timestamp":  e.timestamp,
        }
        for e in book.events
    ]
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
    return df


# ─────────────────────────────────────────────
#  Analysis helpers
# ─────────────────────────────────────────────

def mid_price_series(book: OrderBook) -> pd.Series:
    """Return a time-indexed Series of mid prices from the event log."""
    df = events_to_df(book)
    if df.empty:
        return pd.Series(dtype=float)
    s = df.set_index("timestamp")["mid_price"].dropna()
    return s


def spread_series(book: OrderBook) -> pd.Series:
    """Return a time-indexed Series of spreads from the event log."""
    df = events_to_df(book)
    if df.empty:
        return pd.Series(dtype=float)
    s = df.set_index("timestamp")["spread"].dropna()
    return s


def trade_price_series(book: OrderBook) -> pd.Series:
    """Return a time-indexed Series of trade (fill) prices."""
    df = fills_to_df(book)
    if df.empty:
        return pd.Series(dtype=float)
    return df.set_index("timestamp")["price"]


def volume_profile(book: OrderBook, bins: int = 20) -> pd.DataFrame:
    """
    Compute volume traded at each price bin (market profile).
    Returns a DataFrame with columns: price_bin, volume.
    """
    df = fills_to_df(book)
    if df.empty:
        return pd.DataFrame()
    df["price_bin"] = pd.cut(df["price"], bins=bins)
    return (
        df.groupby("price_bin", observed=True)["quantity"]
        .sum()
        .reset_index()
        .rename(columns={"quantity": "volume"})
    )


def event_type_counts(book: OrderBook) -> pd.Series:
    """Count of each event type."""
    df = events_to_df(book)
    if df.empty:
        return pd.Series(dtype=int)
    return df["event_type"].value_counts()


def print_summary(book: OrderBook):
    """Print a human-readable summary of book activity."""
    fills_df  = fills_to_df(book)
    events_df = events_to_df(book)

    print("── Event Log Summary ───────────────────────")
    if not events_df.empty:
        print(f"  Total events    : {len(events_df)}")
        print("  By type:")
        for etype, count in event_type_counts(book).items():
            print(f"    {etype:<20} {count}")

    print()
    print("── Fill Summary ────────────────────────────")
    if not fills_df.empty:
        print(f"  Total fills     : {len(fills_df)}")
        print(f"  Total volume    : {fills_df['quantity'].sum():.2f}")
        print(f"  VWAP            : {(fills_df['price'] * fills_df['quantity']).sum() / fills_df['quantity'].sum():.4f}")
        print(f"  Price range     : {fills_df['price'].min():.4f} – {fills_df['price'].max():.4f}")
    else:
        print("  No fills recorded.")

    print()
    print("── Spread Summary ──────────────────────────")
    valid_spreads = events_df["spread"].dropna() if not events_df.empty else pd.Series(dtype=float)
    if not valid_spreads.empty:
        print(f"  Mean spread     : {valid_spreads.mean():.4f}")
        print(f"  Median spread   : {valid_spreads.median():.4f}")
        print(f"  Min spread      : {valid_spreads.min():.4f}")
        print(f"  Max spread      : {valid_spreads.max():.4f}")
    else:
        print("  No spread data.")


# ─────────────────────────────────────────────
#  Smoke test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    from orderBook import OrderBook
    from order_flow_simulator import OrderFlowSimulator, SimulatorConfig

    book = OrderBook("AAPL")
    sim  = OrderFlowSimulator(book, SimulatorConfig(seed=42))
    sim.run(1000)

    print_summary(book)

    print()
    print("── Fill DataFrame (head) ───────────────────")
    print(fills_to_df(book).head(10))

    print()
    print("── Volume Profile ──────────────────────────")
    print(volume_profile(book, bins=10))