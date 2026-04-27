"""
Special logger class to allow the backtester tool (credit to @jmerle)
to capture logs.
"""


from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
from typing import List, Any
import json


##### LOGGER REPLACE FOR FINAL SUBMISSION #####
class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )

        # We truncate state.traderData, trader_data, and self.logs to the same max. length to fit the log limit
        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self.to_json(
                [
                    self.compress_state(state, self.truncate(state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )

        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])

        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]

        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )

        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        if observations is None:
            return [{}, {}]
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
            ]

        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])

        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        lo, hi = 0, min(len(value), max_length)
        out = ""

        while lo <= hi:
            mid = (lo + hi) // 2

            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."

            encoded_candidate = json.dumps(candidate)

            if len(encoded_candidate) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1

        return out
##### LOGGER REPLACE FOR FINAL SUBMISSION #####


logger = Logger()




from datamodel import Time, Product, Symbol, Position, UserId, \
    ObservationValue, Listing, Observation, Order, OrderDepth, \
    Trade, TradingState, ProsperityEncoder
import jsonpickle
import math

class NormalTrader:
    def load_state(self, state: TradingState):
        self.state = state

        # User-defined data from previous time step
        self.data = None if state.traderData == "" else \
            jsonpickle.loads(state.traderData)

        # Divide by 100 so each step is 1 increment of time
        self.ts = state.timestamp // 100

        # Mapping from product to its denomination
        # TODO: This is not yet used; update later once enough info.
        self.denomination_map = {
            symbol: listing.denomination
            for symbol, listing in state.listings.items()
        }

        # Mapping from product to its symbol
        # TODO: It could be the case that the datamodel is outdated and
        # some dicts are actually using Product as key but is typed as
        # Symbol (and vice versa). For now, we can assume product ==
        # symbol, so we actually don't use this yet. Update later once
        # we have more info.
        self.symbol_map = {
            listing.product: symbol
            for symbol, listing in state.listings.items()
        }
        # assert all(symbol == listing.product
        #            for symbol, listing in state.listings.items()), \
        #     "Assumption violated; update code!!!"

        # Buy orders (price, qty) sorted in descending order of price
        # (first = best bid, last = worst bid)
        self.buy_orders = {
            symbol: [] for symbol in self.symbol_map.keys()
        } | {  # default to empty list
            symbol: list(map(lambda t: (round(t[0]), round(t[1])),
                             sorted(order_depth.buy_orders.items(),
                                    reverse=True)))
            for symbol, order_depth in state.order_depths.items()
        }

        # Sell orders (price, qty) sorted in ascending order of price
        # (first = best ask, last = worst ask)
        self.sell_orders = {
            symbol: [] for symbol in self.symbol_map.keys()
        } | {  # default to empty list
            symbol: list(map(lambda t: (round(t[0]), -round(t[1])),
                             sorted(order_depth.sell_orders.items())))
            for symbol, order_depth in state.order_depths.items()
        }

        # Remaining buy orders if matching were to take place
        # In other words, if we were to submit self.orders_to_send,
        # the matching engine will first attempt to match our buy
        # orders with the sell orders in self.sell_orders. The result
        # of that will be self.buy_orders_am (am = after matching).
        # This is useful if we want to market make (for example);
        # simply look at the first element of self.buy_orders_am for
        # the best bid.
        # (has same sorting as self.buy_orders)
        self.buy_orders_am = self.buy_orders.copy()

        # Remaining sell orders if matching were to take place
        # (has same sorting as self.sell_orders)
        self.sell_orders_am = self.sell_orders.copy()

        # Our own trades on the last time step we had any trades;
        # don't care about this for now
        self.own_trades = state.own_trades.copy()
        # sanitize prices and quantities so they are all ints
        for trades in self.own_trades.values():
            for t in trades:
                t.price = round(t.price)
                t.quantity = round(t.quantity)

        # Market trades made on the last time step there were any
        # market trades
        self.market_trades = state.market_trades.copy()
        # sanitize prices and quantities so they are all ints
        for trades in self.market_trades.values():
            for t in trades:
                t.price = round(t.price)
                t.quantity = round(t.quantity)

        # Our current position
        self.position = {
            listing.product: round(state.position.get(listing.product, 0))
            for listing in state.listings.values()
        }

        # Ignore for now
        self.observations = state.observations

        # To be filled in by self._run using self.send_[buy|sell]_order
        self.orders_to_send = {listing.product: []
                               for listing in state.listings.values()}

    def max_buy_orders_left(self, product: Product):
        """
        The maximum number of buy orders we can still place for the
        given product, such that position limits are not violated.
        """
        # It shouldn't be negative but just in case...
        value = self.pos_limits[product] - self.position[product] - \
            sum(o.quantity for o in self.orders_to_send[product]
                if o.quantity > 0)
        if value < 0:
            logger.print(f"WARNING: bug in max_buy_orders_left")
        return max(0, value)

    def max_sell_orders_left(self, product: Product):
        """
        The maximum number of sell orders we can still place for the
        given product, such that position limits are not violated.
        """
        # It shouldn't be negative but just in case... we use max().
        value = self.pos_limits[product] + self.position[product] + \
            sum(o.quantity for o in self.orders_to_send[product]
                if o.quantity < 0)
        if value < 0:
            logger.print(f"WARNING: bug in max_sell_orders_left")
        return max(0, value)

    def worst_bid(self, product: Product):
        """
        Returns the lowest bid price AFTER MATCHING (up to the current
        line of code).
        """
        if self.buy_orders[product]:
            return self.buy_orders[product][-1][0]
        return None

    def worst_ask(self, product: Product):
        """
        Returns the highest ask price AFTER MATCHING (up to the current
        line of code).
        """
        if self.sell_orders[product]:
            return self.sell_orders[product][-1][0]
        return None

    def best_bid(self, product: Product):
        """
        This is AFTER MATCHING (up to the current line of code).
        """
        if self.buy_orders_am[product]:
            return self.buy_orders_am[product][0][0]
        return None

    def best_ask(self, product: Product):
        """
        This is AFTER MATCHING (up to the current line of code).
        """
        if self.sell_orders_am[product]:
            return self.sell_orders_am[product][0][0]
        return None

    def best_bid_qty(self, product: Product):
        """
        This is AFTER MATCHING (up to the current line of code).
        """
        if self.buy_orders_am[product]:
            return self.buy_orders_am[product][0][1]
        return None

    def best_ask_qty(self, product: Product):
        """
        This is AFTER MATCHING (up to the current line of code).
        """
        if self.sell_orders_am[product]:
            return self.sell_orders_am[product][0][1]
        return None

    def write_data(self, data = None):
        """
        Call this to write data for the next timestamp. Make sure the
        old data is no longer used.
        """
        self._next_data_json = "" if data is None else jsonpickle.dumps(data)

    def send_buy_order(self, product: Product, price: int,
                       quantity: int, msg: str = None):
        """
        Places a buy order, returns the quantity actually bought (it can
        be less than the quantity specified if it would violate position
        limits).
        """
        if quantity > self.max_buy_orders_left(product):
            logger.print(f"WARNING: send_buy_order for {quantity} "
                         f"{product} exceeds position limits")
            quantity = self.max_buy_orders_left(product)

        self.orders_to_send[product].append(
            Order(product, price, quantity)
        )
        unmatched_qty = quantity
        while unmatched_qty > 0:
            best_ask = self.best_ask(product)
            if best_ask is None or best_ask > price:
                break
            best_ask_qty = self.best_ask_qty(product)
            match_qty = min(unmatched_qty, best_ask_qty)
            unmatched_qty -= match_qty
            if best_ask_qty == match_qty:
                self.sell_orders_am[product].pop(0)
            else:
                self.sell_orders_am[product][0] = \
                    (best_ask, best_ask_qty - match_qty)
            if msg:
                logger.print(f"BUY (EXPECT MATCH) {match_qty} {product} @ {best_ask} ({msg})")
        
        if msg and unmatched_qty > 0:
            logger.print(f"BUY (UNMATCHED) {unmatched_qty} {product} @ {price} ({msg})")

    def send_sell_order(self, product: Product, price: int,
                        quantity: int, msg: str = None):
        """
        Places a sell order, returns the quantity actually sold (it can
        be less than the quantity specified if it would violate position
        limits).
        """
        if quantity > self.max_sell_orders_left(product):
            logger.print(f"WARNING: send_sell_order for {quantity} "
                         f"{product} exceeds position limits")
            quantity = self.max_sell_orders_left(product)

        self.orders_to_send[product].append(Order(product, price, -quantity))
        unmatched_qty = quantity
        while unmatched_qty > 0:
            best_bid = self.best_bid(product)
            if best_bid is None or best_bid < price:
                break
            best_bid_qty = self.best_bid_qty(product)
            match_qty = min(unmatched_qty, best_bid_qty)
            unmatched_qty -= match_qty
            if best_bid_qty == match_qty:
                self.buy_orders_am[product].pop(0)
            else:
                self.buy_orders_am[product][0] = \
                    (best_bid, best_bid_qty - match_qty)
            if msg:
                logger.print(f"SELL (EXPECT MATCH) {match_qty} {product} @ {best_bid} ({msg})")
        
        if msg and unmatched_qty > 0:
            logger.print(f"SELL (UNMATCHED) {unmatched_qty} {product} @ {price} ({msg})")

    def match_buy_with_sell(self, product: Product, acceptable_price: int,
                            max_quantity: int = None, max_depth: int = None,
                            msg: str = None):
        """
        Create as many buy orders as possible to match existing
        unmatched sell orders, while respecting position limits and
        applying the given constraints.

        acceptable_price -- max ask price we are willing to buy

        max_quantity -- max quantity we are willing to buy (if None,
        max is still capped by position limits)

        max_depth -- max depth (number of distinct prices) of the order
        book we are willing to buy (if None, no max depth)

        Returns the quantity actually bought.
        """ 
        if max_quantity is None:
            max_quantity = self.max_buy_orders_left(product)
        else:
            max_quantity = min(max_quantity, self.max_buy_orders_left(product))

        qty_left = max_quantity
        depth = 0
        while qty_left > 0 and (max_depth is None or depth < max_depth):
            best_ask = self.best_ask(product)
            if best_ask is None or best_ask > acceptable_price:
                break
            best_ask_qty = self.best_ask_qty(product)
            buy_qty = min(qty_left, best_ask_qty)
            self.send_buy_order(product, best_ask, buy_qty, msg)
            qty_left -= buy_qty
            depth += 1

        return max_quantity - qty_left

    def match_sell_with_buy(self, product: Product, acceptable_price: int,
                            max_quantity: int = None, max_depth: int = None,
                            msg: str = None):
        """
        Same as match_buy_with_sell, but for sell orders.

        acceptable_price -- min bid price we are willing to sell

        max_quantity -- max quantity we are willing to sell (if None,
        max is still capped by position limits)

        max_depth -- max depth (number of distinct prices) of the order
        book we are willing to sell (if None, no max depth)

        Returns the quantity actually sold.
        """
        if max_quantity is None:
            max_quantity = self.max_sell_orders_left(product)
        else:
            max_quantity = min(max_quantity, self.max_sell_orders_left(product))
        
        qty_left = max_quantity
        depth = 0
        while qty_left > 0 and (max_depth is None or depth < max_depth):
            best_bid = self.best_bid(product)
            if best_bid is None or best_bid < acceptable_price:
                break
            best_bid_qty = self.best_bid_qty(product)
            sell_qty = min(qty_left, best_bid_qty)
            self.send_sell_order(product, best_bid, sell_qty, msg)
            qty_left -= sell_qty
            depth += 1

        return max_quantity - qty_left

    def _run(self):
        raise NotImplementedError

    def run(self, state: TradingState):
        try:
            self.load_state(state)
            self._run()
            trader_data = "" if self.data is None else jsonpickle.dumps(self.data)
            logger.flush(state, self.orders_to_send, 0, trader_data)  # no conversions this round
            return self.orders_to_send, 0, trader_data
        except Exception as e:
            # raise e  ##### RAISE REPLACE FOR FINAL SUBMISSION #####
            return {}, 0, ""


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erfc for pure-Python compatibility."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_call_price(S: float, K: float, T: float, sigma: float) -> float:
    """Black-Scholes call price (r=0)."""
    if T <= 0.0:
        return max(S - K, 0.0)
    if sigma <= 0.0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


def bs_delta(S: float, K: float, T: float, sigma: float) -> float:
    """Black-Scholes delta for a call (r=0)."""
    if T <= 0.0:
        return 1.0 if S > K else 0.0
    if sigma <= 0.0:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return _norm_cdf(d1)


def implied_vol(S: float, K: float, T: float, C_market: float,
                lo: float = 0.001, hi: float = 30.0,
                n_iter: int = 50) -> float:
    """
    Bisection-based implied volatility solver.
    Returns NaN if no solution exists in [lo, hi].
    """
    intrinsic = max(S - K, 0.0)
    if C_market <= intrinsic + 1e-4:
        return float("nan")
    f_lo = bs_call_price(S, K, T, lo) - C_market
    f_hi = bs_call_price(S, K, T, hi) - C_market
    if f_lo * f_hi > 0:
        return float("nan")
    for _ in range(n_iter):
        mid = 0.5 * (lo + hi)
        f_mid = bs_call_price(S, K, T, mid) - C_market
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo = mid
            f_lo = f_mid
    return 0.5 * (lo + hi)


class RoundThreeTrader(NormalTrader):
    """
    Base trader for Round 3 with position limits for all products.
    These should be updated once official limits are confirmed.
    """

    # ---- CONFIGURABLE PARAMETERS ----
    # VFX market-making
    VFX_FAIR = 5250          # Long-run mean (updated per-tick using order book)
    VFX_MM_HALF_SPREAD = 3   # Half-spread we quote around fair value
    VFX_MM_SKEW_PER_POS = 0.05  # Ticks of skew per unit of inventory
    VFX_POS_LIMIT = 200

    # HPK market-making
    HPK_FAIR = 9991          # Long-run mean
    HPK_MM_HALF_SPREAD = 7   # Half-spread (spread ~16, so 7 is conservative)
    HPK_MM_SKEW_PER_POS = 0.2
    HPK_EXTREME_THRESH = 50  # Fade aggressively when HPK deviates > this from fair
    HPK_POS_LIMIT = 200

    # Options
    TARGET_IV = 0.21         # Historical mean implied vol ≈ 21 %
    IV_BUY_THRESH = 0.195    # Buy when IV implied by market < this
    IV_SELL_THRESH = 0.225   # Sell when IV implied by market > this
    # Time-to-expiry in years for each round (round n → TTE = (7-n+1) days)
    # Round 1 = day 0 → TTE=7; Round 2 = day 1 → TTE=6; Round 3 = day 2 → TTE=5 …
    DAYS_PER_YEAR = 252.0
    OPTION_POS_LIMIT = 300
    DEEP_OTM_SELL_LIMIT = 50  # max short in VEV_6000 / VEV_6500

    def __init__(self):
        super().__init__()
        self.pos_limits = {
            # Round 2 products kept for safety (ignored if not in state)
            "ASH_COATED_OSMIUM": 80,
            "INTARIAN_PEPPER_ROOT": 80,
            # Round 3 products
            "VELVETFRUIT_EXTRACT": self.VFX_POS_LIMIT,
            "HYDROGEL_PACK": self.HPK_POS_LIMIT,
            "VEV_4000": self.OPTION_POS_LIMIT,
            "VEV_4500": self.OPTION_POS_LIMIT,
            "VEV_5000": self.OPTION_POS_LIMIT,
            "VEV_5100": self.OPTION_POS_LIMIT,
            "VEV_5200": self.OPTION_POS_LIMIT,
            "VEV_5300": self.OPTION_POS_LIMIT,
            "VEV_5400": self.OPTION_POS_LIMIT,
            "VEV_5500": self.OPTION_POS_LIMIT,
            "VEV_6000": self.OPTION_POS_LIMIT,
            "VEV_6500": self.OPTION_POS_LIMIT,
        }

    # ------------------------------------------------------------------
    # Helper: mid price from order book (falls back to a constant if OB empty)
    # ------------------------------------------------------------------
    def _ob_mid(self, product: Product, fallback: float) -> float:
        bb = self.best_bid(product)
        ba = self.best_ask(product)
        if bb is not None and ba is not None:
            return (bb + ba) / 2.0
        if bb is not None:
            return float(bb)
        if ba is not None:
            return float(ba)
        return fallback

    # ------------------------------------------------------------------
    # Strategy 1: VELVETFRUIT_EXTRACT mean-reversion market-making
    # ------------------------------------------------------------------
    def trade_velvetfruit_extract(self):
        product = "VELVETFRUIT_EXTRACT"
        pos = self.position.get(product, 0)

        # Use live OB mid as fair value; fall back to historical mean
        fair = self._ob_mid(product, self.VFX_FAIR)

        # Inventory skew: tighten the side we want to reduce, widen the other
        skew = self.VFX_MM_SKEW_PER_POS * pos  # positive pos → lower bid/ask

        buy_price  = round(fair - self.VFX_MM_HALF_SPREAD - skew)
        sell_price = round(fair + self.VFX_MM_HALF_SPREAD - skew)

        # Step 1: take profitable fills first (market-take at fair ± small offset)
        take_buy_threshold  = round(fair - 1)
        take_sell_threshold = round(fair + 1)
        self.match_buy_with_sell(product, take_buy_threshold,
                                 msg="VFX take-buy")
        self.match_sell_with_buy(product, take_sell_threshold,
                                 msg="VFX take-sell")

        # Step 2: passive market-making quotes
        buy_qty  = self.max_buy_orders_left(product)
        sell_qty = self.max_sell_orders_left(product)

        if buy_qty > 0:
            self.send_buy_order(product, buy_price, buy_qty, msg="VFX MM bid")
        if sell_qty > 0:
            self.send_sell_order(product, sell_price, sell_qty, msg="VFX MM ask")

    # ------------------------------------------------------------------
    # Strategy 2: HYDROGEL_PACK mean-reversion market-making with fade
    # ------------------------------------------------------------------
    def trade_hydrogel_pack(self):
        product = "HYDROGEL_PACK"
        pos = self.position.get(product, 0)

        fair = self._ob_mid(product, self.HPK_FAIR)
        deviation = fair - self.HPK_FAIR

        # Aggressive fade: if price is very far from fair, take the market
        if deviation > self.HPK_EXTREME_THRESH:
            # Price is high → sell aggressively
            self.match_sell_with_buy(product, round(fair - 2),
                                     msg="HPK extreme-fade sell")
        elif deviation < -self.HPK_EXTREME_THRESH:
            # Price is low → buy aggressively
            self.match_buy_with_sell(product, round(fair + 2),
                                     msg="HPK extreme-fade buy")

        # Normal market-making
        skew = self.HPK_MM_SKEW_PER_POS * pos
        buy_price  = round(fair - self.HPK_MM_HALF_SPREAD - skew)
        sell_price = round(fair + self.HPK_MM_HALF_SPREAD - skew)

        buy_qty  = self.max_buy_orders_left(product)
        sell_qty = self.max_sell_orders_left(product)

        if buy_qty > 0:
            self.send_buy_order(product, buy_price, buy_qty, msg="HPK MM bid")
        if sell_qty > 0:
            self.send_sell_order(product, sell_price, sell_qty, msg="HPK MM ask")

    # ------------------------------------------------------------------
    # Strategy 3: Sell deep-OTM options (VEV_6000, VEV_6500) at floor
    # These are worth ~0 per BS but market floor = 0.5, free premium.
    # ------------------------------------------------------------------
    def trade_deep_otm_options(self):
        for product in ("VEV_6000", "VEV_6500"):
            pos = self.position.get(product, 0)
            # Only sell (short), capped at DEEP_OTM_SELL_LIMIT
            max_sell = min(self.max_sell_orders_left(product),
                           self.DEEP_OTM_SELL_LIMIT + pos)  # pos is negative when short
            if max_sell <= 0:
                continue

            # Sell at the best bid (0 or 1); we'll take any bid ≥ 1
            best_bid = self.best_bid(product)
            if best_bid is not None and best_bid >= 1:
                sell_qty = min(max_sell, self.best_bid_qty(product) or max_sell)
                self.send_sell_order(product, best_bid, sell_qty,
                                     msg=f"{product} deep-OTM sell")
            else:
                # Post a passive ask at 1 (min meaningful price)
                if self.max_sell_orders_left(product) > 0:
                    self.send_sell_order(product, 1,
                                         min(max_sell, 25),
                                         msg=f"{product} deep-OTM passive ask")

    # ------------------------------------------------------------------
    # Strategy 4: Near-ATM option quoting via Black-Scholes fair value
    # Vouchers: VEV_5200, VEV_5300, VEV_5400, VEV_5500
    # We compute BS fair value and quote ±half_spread around it.
    # We also check implied vol of best bid/ask and take if mispriced.
    # ------------------------------------------------------------------
    def trade_atm_options(self, S: float, T: float):
        """
        S: current VFX spot mid-price
        T: time to expiry in years
        """
        strikes = {
            "VEV_5200": 5200,
            "VEV_5300": 5300,
            "VEV_5400": 5400,
            "VEV_5500": 5500,
        }
        # Quote half-spread for options: 1 tick (options have 1–3 tick spread)
        OPT_HALF_SPREAD = 1

        for product, K in strikes.items():
            fair_c = bs_call_price(S, K, T, self.TARGET_IV)
            fair_c_rounded = round(fair_c)
            # Ensure fair_c >= intrinsic + 1 to avoid placing silly quotes
            intrinsic = max(round(S) - K, 0)
            fair_c_rounded = max(fair_c_rounded, intrinsic + 1)

            pos = self.position.get(product, 0)

            # --- Market-taking: buy if market ask implies low IV ---
            best_ask = self.best_ask(product)
            if best_ask is not None:
                iv_ask = implied_vol(S, K, T, float(best_ask))
                if not math.isnan(iv_ask) and iv_ask < self.IV_BUY_THRESH:
                    qty = min(self.max_buy_orders_left(product),
                              self.best_ask_qty(product) or 10)
                    if qty > 0:
                        self.send_buy_order(product, best_ask, qty,
                                            msg=f"{product} IV-cheap buy (iv={iv_ask:.2%})")

            # --- Market-taking: sell if market bid implies high IV ---
            best_bid = self.best_bid(product)
            if best_bid is not None:
                iv_bid = implied_vol(S, K, T, float(best_bid))
                if not math.isnan(iv_bid) and iv_bid > self.IV_SELL_THRESH:
                    qty = min(self.max_sell_orders_left(product),
                              self.best_bid_qty(product) or 10)
                    if qty > 0:
                        self.send_sell_order(product, best_bid, qty,
                                             msg=f"{product} IV-rich sell (iv={iv_bid:.2%})")

            # --- Passive quotes around BS fair value ---
            # Skew: lean against inventory
            skew = round(pos * 0.05)
            bid_price = fair_c_rounded - OPT_HALF_SPREAD - skew
            ask_price = fair_c_rounded + OPT_HALF_SPREAD - skew
            bid_price = max(bid_price, intrinsic)  # never quote below intrinsic
            ask_price = max(ask_price, intrinsic + 1)

            buy_qty  = self.max_buy_orders_left(product)
            sell_qty = self.max_sell_orders_left(product)

            if buy_qty > 0:
                self.send_buy_order(product, bid_price, buy_qty,
                                    msg=f"{product} BS-bid @ {bid_price}")
            if sell_qty > 0:
                self.send_sell_order(product, ask_price, sell_qty,
                                     msg=f"{product} BS-ask @ {ask_price}")

    # ------------------------------------------------------------------
    # Strategy 5: Deep-ITM options (VEV_4000, VEV_4500) as VFX proxy /
    # arbitrage. These have delta≈1; fair value = max(S-K, 0).
    # Arb: if option mid deviates > spread_buffer from S-K, take it.
    # ------------------------------------------------------------------
    def trade_deepitm_options(self, S: float):
        arb_products = {
            "VEV_4000": 4000,
            "VEV_4500": 4500,
        }
        ARB_BUFFER = 3  # require >3 ticks mispricing net of spreads

        for product, K in arb_products.items():
            fair = round(S) - K  # intrinsic value (delta≈1, no meaningful TV)
            if fair <= 0:
                continue  # out of the money; skip

            best_ask = self.best_ask(product)
            best_bid = self.best_bid(product)

            # Option is too cheap → buy call, effectively long VFX cheaply
            if best_ask is not None and best_ask < fair - ARB_BUFFER:
                qty = min(self.max_buy_orders_left(product),
                          self.best_ask_qty(product) or 10)
                if qty > 0:
                    self.send_buy_order(product, best_ask, qty,
                                        msg=f"{product} deep-ITM arb buy (fair={fair})")

            # Option is too expensive → sell call (covered by VFX position)
            if best_bid is not None and best_bid > fair + ARB_BUFFER:
                qty = min(self.max_sell_orders_left(product),
                          self.best_bid_qty(product) or 10)
                if qty > 0:
                    self.send_sell_order(product, best_bid, qty,
                                         msg=f"{product} deep-ITM arb sell (fair={fair})")


class Trader(RoundThreeTrader):
    """
    Round 3 Trader.

    Strategies:
      1. VELVETFRUIT_EXTRACT (VFX): mean-reversion market-making with
         inventory skew, taking when ≤1 tick from fair.
      2. HYDROGEL_PACK (HPK): same as VFX, plus aggressive fade when
         price deviates > 50 ticks from long-run mean (~9991).
      3. VEV_6000 / VEV_6500: sell at 1 (BS fair ≈ 0, floor = 0.5–1).
      4. VEV_5200/5300/5400/5500: quote around Black-Scholes fair value
         at target IV=21%; take when market implies IV < 19.5% or > 22.5%.
      5. VEV_4000 / VEV_4500: arbitrage when call deviates > 3 ticks
         from intrinsic (S − K).

    CONFIG keys used: none for Round 3 (kept for backwards compat).
    """

    # Round the current timestamp to a competition "round" (1-indexed).
    # Each round's data covers timestamps 0..999900 (10000 ticks).
    # Round 1 = day_offset 0, Round 2 = day_offset 1, Round 3 = day_offset 2, etc.
    # TTE (days) = 7 − round_number + 1 = 8 − round_number
    # But we don't know round_number at runtime; use traderData to track it.
    # Simpler: calibrate from the data. TTE for round 3 = 5 days.
    CURRENT_ROUND = 3  # UPDATE THIS each round!
    TTE_DAYS = 7 - CURRENT_ROUND + 1  # = 5 days for round 3

    def _compute_tte(self) -> float:
        """Time to expiry in years."""
        tte_days = max(self.TTE_DAYS - self.ts / 10000.0, 0.01)
        return tte_days / self.DAYS_PER_YEAR

    def _vfx_spot(self) -> float:
        """Best estimate of VFX spot price."""
        return self._ob_mid("VELVETFRUIT_EXTRACT", self.VFX_FAIR)

    def _run(self):
        # Initialise persistent data
        if self.data is None:
            self.data = {}

        # Derived quantities
        S = self._vfx_spot()
        T = self._compute_tte()

        logger.print(f"ts={self.ts} S={S:.1f} T={T*252:.2f}d "
                     f"pos_VFX={self.position.get('VELVETFRUIT_EXTRACT',0)} "
                     f"pos_HPK={self.position.get('HYDROGEL_PACK',0)}")

        # Execute strategies in priority order
        # self.trade_velvetfruit_extract()
        # self.trade_hydrogel_pack()
        # self.trade_deep_otm_options()
        self.trade_atm_options(S, T)
        # self.trade_deepitm_options(S)

