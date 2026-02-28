from sortedcontainers import SortedDict
from collections import deque
from order import Side, Order, OrderType

class OrderBook:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids = SortedDict()  # price -> deque of Orders (keyed negative)
        self.asks = SortedDict()  # price -> deque of Orders
        self.orders = {}          # order_id -> Order (for fast lookup/cancel)
        self._order_counter = 0

    def best_bid(self):
        if self.bids:
            return -self.bids.keys()[0]
        return None

    def best_ask(self):
        if self.asks:
            return self.asks.keys()[0]
        return None

    def mid_price(self):
        if self.best_bid() and self.best_ask():
            return (self.best_bid() + self.best_ask()) / 2
        return None

    def spread(self):
        if self.best_bid() and self.best_ask():
            return self.best_ask() - self.best_bid()
        return None
    
    def add_limit_order(self, side, price, quantity):
        self._order_counter += 1
        order = Order(self._order_counter, side, OrderType.LIMIT, price, quantity)
        self.orders[order.order_id] = order

        if side == Side.BID:
            key = -price
            book_side = self.bids
        else:
            key = price
            book_side = self.asks

        if key not in book_side:
            book_side[key] = deque()
        book_side[key].append(order)
        return order.order_id

    def cancel_order(self, order_id):
        if order_id not in self.orders:
            return False
        order = self.orders.pop(order_id)
        key = -order.price if order.side == Side.BID else order.price
        book_side = self.bids if order.side == Side.BID else self.asks
        book_side[key].remove(order)
        if not book_side[key]:
            del book_side[key]
        return True
    

def main():
    bid = Side.BID
    ask = Side.ASK
    book = OrderBook("SPY")

    book.add_limit_order(bid, 99, 10)
    book.add_limit_order(ask, 101, 10)

    print(book.best_bid())
    print(book.best_ask())
    print(book.spread())
    print(book.mid_price())


if __name__ == "__main__":
    main()