from dataclasses import dataclass, field
from enum import Enum
import time

class Side(Enum):
    BID = "bid"
    ASK = "ask"

class OrderType(Enum):
    LIMIT = "limit"
    MARKET = "market"

@dataclass
class Order:
    order_id: int
    side: Side
    order_type: OrderType
    price: float        # None for market orders
    quantity: float
    timestamp: float = field(default_factory=time.time)
    filled_quantity: float = 0.0

    @property
    def remaining_quantity(self):
        return self.quantity - self.filled_quantity