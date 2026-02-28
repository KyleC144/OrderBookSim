import unittest
from src.orderBook import OrderBook, Side

class OrderBookTestCase(unittest.TestCase):
    def setUp(self):
        ticker = "SPY"
        self.book = OrderBook(ticker)
        self.bid = Side.BID
        self.ask = Side.ASK

    def tearDown(self):
        del self.book

    def testEmptyOrderBook(self):
        assert(self.book.best_bid() == None)
        assert(self.book.best_ask() == None)
        assert(self.book.spread() == None)
        assert(self.book.mid_price() == None)

    def testOrderBook(self):
        self.book.add_limit_order(self.bid, 99, 1)
        self.book.add_limit_order(self.ask, 101, 1)

        assert(self.book.best_bid() == 99)
        assert(self.book.best_ask() == 101)
        assert(self.book.spread() == 2)
        assert(self.book.mid_price() == 100)
    
    def testOrderBookCancel(self):
        id1, _ = self.book.add_limit_order(self.bid, 99, 1)
        id2, _ = self.book.add_limit_order(self.ask, 101, 1)

        assert(self.book.best_bid() == 99)
        assert(self.book.best_ask() == 101)
        assert(self.book.spread() == 2)
        assert(self.book.mid_price() == 100)

        self.book.cancel_order(id1)

        assert(self.book.best_bid() == None)
        assert(self.book.best_ask() == 101)
        assert(self.book.spread() == None)
        assert(self.book.mid_price() == None)



if __name__ == '__main__':
    unittest.main()