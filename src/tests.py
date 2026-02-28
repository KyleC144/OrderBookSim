import unittest
from orderBook import OrderBook, Side
from order_flow_simulator import OrderFlowSimulator, SimulatorConfig
from event_log import volume_profile, fills_to_df

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
    
    def testSim(self):
        sim = OrderFlowSimulator(self.book, SimulatorConfig(seed=42))
        sim.run(1000)

        assert(fills_to_df(self.book).iloc[0].to_dict()["price"] == 100.0201)

        assert(volume_profile(self.book, bins=10)["volume"].to_string(index=False) == """389.0
293.0
233.0
179.0
117.0
 98.0
 43.0
 39.0
109.0
129.0""")



if __name__ == '__main__':
    unittest.main()