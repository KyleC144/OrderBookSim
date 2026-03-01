from dataclasses import dataclass, field
from enum import Enum
from collections import deque
from sortedcontainers import SortedDict
import time

class Side(Enum):
    BID = "bid"
    ASK = "ask"


class OrderType(Enum):
    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(Enum):
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"


class EventType(Enum):
    LIMIT_PLACED  = "limit_placed"
    MARKET_PLACED = "market_placed"
    FILL          = "fill"
    CANCEL        = "cancel"

@dataclass
class Order:
    order_id: int
    side: Side
    order_type: OrderType
    price: float | None       # None for market orders
    quantity: float
    timestamp: float = field(default_factory=time.time)
    filled_quantity: float = 0.0
    status: OrderStatus = OrderStatus.OPEN

    @property
    def remaining_quantity(self) -> float:
        return self.quantity - self.filled_quantity

    def __repr__(self):
        return (
            f"Order(id={self.order_id}, {self.side.value}, {self.order_type.value}, "
            f"price={self.price}, qty={self.quantity}, filled={self.filled_quantity}, "
            f"status={self.status.value})"
        )


@dataclass
class Fill:
    fill_id: int
    maker_order_id: int
    taker_order_id: int
    price: float
    quantity: float
    timestamp: float = field(default_factory=time.time)

    def __repr__(self):
        return (
            f"Fill(id={self.fill_id}, maker={self.maker_order_id}, "
            f"taker={self.taker_order_id}, price={self.price}, qty={self.quantity})"
        )


@dataclass
class Event:
    event_id: int
    event_type: EventType
    timestamp: float
    order_id: int
    side: Side | None       = None
    price: float | None     = None
    quantity: float | None  = None
    fill_id: int | None     = None   # populated for FILL events
    mid_price: float | None = None   # snapshot of mid at event time
    spread: float | None    = None   # snapshot of spread at event time

    def __repr__(self):
        return (
            f"Event(id={self.event_id}, {self.event_type.value}, "
            f"order={self.order_id}, price={self.price}, qty={self.quantity}, "
            f"mid={round(self.mid_price, 4) if self.mid_price else None})"
        )


class OrderBook:
    def __init__(self, symbol: str):
        self.symbol = symbol

        # Bids: keyed by -price  →  index[0] = best (highest) bid
        # Asks: keyed by +price  →  index[0] = best (lowest)  ask
        self.bids: SortedDict = SortedDict()
        self.asks: SortedDict = SortedDict()

        # Fast lookup: order_id → Order
        self.orders: dict[int, Order] = {}

        # Logs
        self.fills:  list[Fill]  = []
        self.events: list[Event] = []

        self._order_counter: int = 0
        self._fill_counter:  int = 0
        self._event_counter: int = 0

    # ── Accessors ──────────────────────────────

    def best_bid(self) -> float | None:
        return -self.bids.keys()[0] if self.bids else None

    def best_ask(self) -> float | None:
        return self.asks.keys()[0] if self.asks else None

    def mid_price(self) -> float | None:
        bb, ba = self.best_bid(), self.best_ask()
        return (bb + ba) / 2 if bb is not None and ba is not None else None

    def spread(self) -> float | None:
        bb, ba = self.best_bid(), self.best_ask()
        return ba - bb if bb is not None and ba is not None else None

    def depth(self, levels: int = 5) -> dict:
        bids_out = [
            (-key, sum(o.remaining_quantity for o in q))
            for key, q in list(self.bids.items())[:levels]
        ]
        asks_out = [
            (key, sum(o.remaining_quantity for o in q))
            for key, q in list(self.asks.items())[:levels]
        ]
        return {"bids": bids_out, "asks": asks_out}

    # ── Internal counters ──────────────────────

    def _next_order_id(self) -> int:
        self._order_counter += 1
        return self._order_counter

    def _next_fill_id(self) -> int:
        self._fill_counter += 1
        return self._fill_counter

    def _next_event_id(self) -> int:
        self._event_counter += 1
        return self._event_counter

    # ── Internal helpers ───────────────────────

    def _book_side_and_key(self, side: Side, price: float):
        return (self.bids, -price) if side == Side.BID else (self.asks, price)

    def _add_to_book(self, order: Order):
        book, key = self._book_side_and_key(order.side, order.price)
        if key not in book:
            book[key] = deque()
        book[key].append(order)
        self.orders[order.order_id] = order

    def _log_event(
        self,
        event_type: EventType,
        order: Order,
        fill: Fill | None = None,
    ):
        self.events.append(Event(
            event_id   = self._next_event_id(),
            event_type = event_type,
            timestamp  = time.time(),
            order_id   = order.order_id,
            side       = order.side,
            price      = order.price,
            quantity   = order.quantity,
            fill_id    = fill.fill_id if fill else None,
            mid_price  = self.mid_price(),
            spread     = self.spread(),
        ))

    def _record_fill(self, maker: Order, taker: Order, price: float, qty: float) -> Fill:
        fill = Fill(
            fill_id        = self._next_fill_id(),
            maker_order_id = maker.order_id,
            taker_order_id = taker.order_id,
            price          = price,
            quantity       = qty,
        )
        self.fills.append(fill)

        for order in (maker, taker):
            order.filled_quantity += qty
            order.status = (
                OrderStatus.FILLED if order.remaining_quantity == 0
                else OrderStatus.PARTIALLY_FILLED
            )

        # Log a FILL event keyed to the taker
        self._log_event(EventType.FILL, taker, fill)
        return fill

    # ── Matching engine ────────────────────────

    def _match(self, incoming: Order) -> list[Fill]:
        fills = []

        if incoming.side == Side.BID:
            opposing_book = self.asks
            def crosses(ip, rp):
                return True if incoming.order_type == OrderType.MARKET else ip >= rp
        else:
            opposing_book = self.bids
            def crosses(ip, rp):
                return True if incoming.order_type == OrderType.MARKET else ip <= rp

        while incoming.remaining_quantity > 0 and opposing_book:
            best_key     = opposing_book.keys()[0]
            resting_price = best_key if incoming.side == Side.BID else -best_key

            if not crosses(incoming.price, resting_price):
                break

            level_queue: deque = opposing_book[best_key]

            while incoming.remaining_quantity > 0 and level_queue:
                resting  = level_queue[0]
                fill_qty = min(incoming.remaining_quantity, resting.remaining_quantity)
                fill     = self._record_fill(resting, incoming, resting_price, fill_qty)
                fills.append(fill)

                if resting.remaining_quantity == 0:
                    level_queue.popleft()
                    self.orders.pop(resting.order_id, None)

            if not level_queue:
                del opposing_book[best_key]

        # Rest any unfilled quantity
        if incoming.remaining_quantity > 0 and incoming.order_type == OrderType.LIMIT:
            self._add_to_book(incoming)
        elif incoming.remaining_quantity > 0 and incoming.order_type == OrderType.MARKET:
            if incoming.filled_quantity > 0:
                incoming.status = OrderStatus.PARTIALLY_FILLED

        return fills

    # ── Public API ─────────────────────────────

    def add_limit_order(self, side: Side, price: float, quantity: float) -> tuple[int, list[Fill]]:
        """Submit a limit order. Returns (order_id, fills)."""
        order = Order(
            order_id   = self._next_order_id(),
            side       = side,
            order_type = OrderType.LIMIT,
            price      = price,
            quantity   = quantity,
        )
        self._log_event(EventType.LIMIT_PLACED, order)
        fills = self._match(order)
        return order.order_id, fills

    def add_market_order(self, side: Side, quantity: float) -> tuple[int, list[Fill]]:
        """Submit a market order. Returns (order_id, fills)."""
        order = Order(
            order_id   = self._next_order_id(),
            side       = side,
            order_type = OrderType.MARKET,
            price      = None,
            quantity   = quantity,
        )
        self._log_event(EventType.MARKET_PLACED, order)
        fills = self._match(order)
        return order.order_id, fills

    def cancel_order(self, order_id: int) -> bool:
        """Cancel a resting limit order. Returns True if successful."""
        if order_id not in self.orders:
            return False
        order = self.orders.pop(order_id)
        book, key = self._book_side_and_key(order.side, order.price)
        try:
            book[key].remove(order)
        except ValueError:
            return False
        if not book[key]:
            del book[key]
        order.status = OrderStatus.CANCELLED
        self._log_event(EventType.CANCEL, order)
        return True

    # ── Display ────────────────────────────────

    def __repr__(self):
        d = self.depth(5)
        lines = [
            f"OrderBook({self.symbol})  "
            f"mid={round(self.mid_price(), 4) if self.mid_price() else 'N/A'}  "
            f"spread={round(self.spread(), 4) if self.spread() else 'N/A'}"
        ]
        lines.append("  ASKS:")
        for price, qty in reversed(d["asks"]):
            lines.append(f"    {price:>10.4f}  {qty:>8.2f}")
        lines.append("  BIDS:")
        for price, qty in d["bids"]:
            lines.append(f"    {price:>10.4f}  {qty:>8.2f}")
        return "\n".join(lines)


if __name__ == "__main__":
    book = OrderBook("AAPL")

    book.add_limit_order(Side.ASK, 101.00, 10)
    book.add_limit_order(Side.ASK, 101.50,  5)
    book.add_limit_order(Side.ASK, 102.00,  8)
    book.add_limit_order(Side.BID, 100.00, 10)
    book.add_limit_order(Side.BID,  99.50,  5)
    book.add_limit_order(Side.BID,  99.00,  8)

    print(book)
    print()

    print("--- Aggressive limit buy @ 101.60, qty=12 ---")
    _, fills = book.add_limit_order(Side.BID, 101.60, 12)
    for f in fills:
        print(" ", f)
    print()

    print("--- Market sell qty=7 ---")
    _, fills = book.add_market_order(Side.ASK, 7)
    for f in fills:
        print(" ", f)
    print()

    print(book)
    print(f"\nTotal events logged: {len(book.events)}")
    print(f"Total fills logged:  {len(book.fills)}")