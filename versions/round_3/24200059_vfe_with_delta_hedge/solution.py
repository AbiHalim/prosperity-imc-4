##### LOGGER #####
from core.logger import logger
##### LOGGER #####
##### CONFIG #####
CONFIG = {}
##### CONFIG #####


from datamodel import Time, Product, Symbol, Position, UserId, \
    ObservationValue, Listing, Observation, Order, OrderDepth, \
    Trade, TradingState, ProsperityEncoder
import jsonpickle


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

import math


class RoundThreeTrader(NormalTrader):

    # ---- CONFIGURABLE PARAMETERS ----
    # VFX market-making
    VFX_FAIR = 5250          # Long-run mean (updated per-tick using order book)
    VFX_MM_HALF_SPREAD = 3   # Half-spread we quote around fair value
    VFX_MM_SKEW_PER_POS = 0.05  # Ticks of skew per unit of inventory
    VFX_POS_LIMIT = 200

    # Options
    TARGET_IV = 0.21         # Historical mean implied vol ≈ 21 %
    DAYS_PER_YEAR = 252.0
    OPTION_POS_LIMIT = 300

    def __init__(self):
        super().__init__()
        self.pos_limits = {
            "VELVETFRUIT_EXTRACT": self.VFX_POS_LIMIT,
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


class Trader(RoundThreeTrader):

    # ---- HEDGE PARAMETERS ----
    # Primary hedging instrument. VEV_5300 chosen because:
    #   - Nearest ATM above spot (~5250), delta ≈ 0.38
    #   - ~2-tick bid-ask spread (cheapest to trade)
    #   - Real time value so the hedge actually works
    HEDGE_PRODUCT = "VEV_5300"
    HEDGE_STRIKE  = 5300

    # Only rebalance when net delta drifts outside this band.
    # Too tight → pays option spread every tick (expensive).
    # Too wide  → too much unhedged directional exposure.
    # At VFX_POS_LIMIT=200, delta≈0.38 → max drift ≈ 200 before fully capped.
    # 20 means we act when unhedged exposure exceeds ~10% of max.
    DELTA_THRESHOLD = 20

    # All strikes we account for when computing total portfolio delta
    ALL_OPTION_STRIKES = {
        "VEV_4000": 4000, "VEV_4500": 4500,
        "VEV_5000": 5000, "VEV_5100": 5100,
        "VEV_5200": 5200, "VEV_5300": 5300,
        "VEV_5400": 5400, "VEV_5500": 5500,
        "VEV_6000": 6000, "VEV_6500": 6500,
    }

    # ---- BLACK-SCHOLES HELPERS (pure stdlib, competition-server safe) ----

    @staticmethod
    def _norm_cdf(x: float) -> float:
        return 0.5 * math.erfc(-x / math.sqrt(2.0))

    @staticmethod
    def _bs_call(S: float, K: float, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return max(S - K, 0.0)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return S * Trader._norm_cdf(d1) - K * Trader._norm_cdf(d2)

    @staticmethod
    def _bs_delta(S: float, K: float, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return 1.0 if S > K else 0.0
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
        return Trader._norm_cdf(d1)

    @staticmethod
    def _implied_vol(S: float, K: float, T: float, C_mkt: float) -> float:
        """Bisection implied-vol solver. Returns nan if no solution."""
        intrinsic = max(S - K, 0.0)
        if C_mkt <= intrinsic + 1e-4:
            return float("nan")
        lo, hi = 0.001, 30.0
        f_lo = Trader._bs_call(S, K, T, lo) - C_mkt
        f_hi = Trader._bs_call(S, K, T, hi) - C_mkt
        if f_lo * f_hi > 0:
            return float("nan")
        for _ in range(50):
            mid = 0.5 * (lo + hi)
            f_mid = Trader._bs_call(S, K, T, mid) - C_mkt
            if f_lo * f_mid <= 0:
                hi = mid
            else:
                lo, f_lo = mid, f_mid
        return 0.5 * (lo + hi)

    # ---- STATE HELPERS ----

    def _tte(self) -> float:
        """
        Time-to-expiry in years.
        TTE shrinks as self.ts increases within a round.
        UPDATE CURRENT_ROUND before each submission.
        """
        CURRENT_ROUND = 3          # ← UPDATE THIS each round (1-indexed)
        tte_days = max((8 - CURRENT_ROUND) - self.ts / 10000.0, 1e-3)
        return tte_days / self.DAYS_PER_YEAR

    def _vfx_mid(self) -> float:
        """Live VFX mid-price; falls back to historical mean if OB is empty."""
        bb = self.best_bid("VELVETFRUIT_EXTRACT")
        ba = self.best_ask("VELVETFRUIT_EXTRACT")
        if bb is not None and ba is not None:
            return (bb + ba) / 2.0
        return float(self.VFX_FAIR)

    def _portfolio_delta(self, S: float, T: float) -> float:
        """
        Total delta of all open positions.

        delta = pos_VFX * 1.0
              + Σ (pos_option_i * bs_delta(S, K_i, T, σ))

        Positive delta  →  net long VFX exposure  (want to sell calls to hedge)
        Negative delta  →  net short VFX exposure (want to buy calls to hedge)
        """
        delta = float(self.position.get("VELVETFRUIT_EXTRACT", 0))
        for product, K in self.ALL_OPTION_STRIKES.items():
            pos = self.position.get(product, 0)
            if pos != 0:
                delta += pos * self._bs_delta(S, K, T, self.TARGET_IV)
        return delta

    # ---- STRATEGY 1: VFX market-making ----

    def mm_velvetfruit_extract(self):
        product = "VELVETFRUIT_EXTRACT"
        mm_threshold = 100

        # Fair price = based on historical mean, PROBABLY NOT a good idea
        fair_price = self.VFX_FAIR
        current_pos = self.position[product]

        # 1. Execute profitable trades always.
        self.match_buy_with_sell(product, fair_price)
        self.match_sell_with_buy(product, fair_price)

        # 2. Market make around the fair price, but turn off one side
        # if position is too skewed.
        best_bid = self.best_bid(product)
        if best_bid is not None and best_bid < fair_price \
        and current_pos < mm_threshold:
            self.send_buy_order(product, best_bid + 1,
                                self.max_buy_orders_left(product))

        best_ask = self.best_ask(product)
        if best_ask is not None and best_ask > fair_price \
        and current_pos > -mm_threshold:
            self.send_sell_order(product, best_ask - 1,
                                 self.max_sell_orders_left(product))

    # ---- STRATEGY 2: Delta hedging via VEV_5300 ----

    def hedge_delta(self, S: float, T: float):
        """
        After market-making VFX, our inventory creates a net delta
        (directional exposure to VFX price). This method offsets that
        exposure by trading VEV_5300 call options.

        Long VFX inventory (+delta) → sell calls → adds −delta.
        Short VFX inventory (−delta) → buy calls  → adds +delta.

        We only act when the drift exceeds DELTA_THRESHOLD, to avoid
        paying the option bid-ask spread every single tick.
        """
        net_delta = self._portfolio_delta(S, T)
        logger.print(f"  net_delta={net_delta:.1f}")

        if abs(net_delta) <= self.DELTA_THRESHOLD:
            return  # comfortably within tolerance

        # BS delta of one VEV_5300 contract at current S, T, σ
        contract_delta = self._bs_delta(S, self.HEDGE_STRIKE, T, self.TARGET_IV)
        if contract_delta < 0.01:
            return  # degenerate (e.g. TTE ~0 and deep OTM), skip

        # Number of contracts needed to return inside the threshold band
        # We target reducing |net_delta| to just inside DELTA_THRESHOLD
        target_reduction = abs(net_delta) - self.DELTA_THRESHOLD
        contracts_needed = max(1, round(target_reduction / contract_delta))

        if net_delta > self.DELTA_THRESHOLD:
            # Too long → sell calls
            qty = min(contracts_needed, self.max_sell_orders_left(self.HEDGE_PRODUCT))
            if qty <= 0:
                return
            # Prefer hitting the existing best bid for immediate fill.
            # Fall back to a passive limit at BS fair value if no bid.
            best_bid = self.best_bid(self.HEDGE_PRODUCT)
            if best_bid is not None and best_bid > 0:
                self.send_sell_order(
                    self.HEDGE_PRODUCT, best_bid, qty,
                    msg=f"hedge sell {qty} (Δ={net_delta:.1f})"
                )
            else:
                fair_c = max(round(self._bs_call(S, self.HEDGE_STRIKE, T, self.TARGET_IV)), 1)
                self.send_sell_order(
                    self.HEDGE_PRODUCT, fair_c, qty,
                    msg=f"hedge passive ask {qty} @ {fair_c} (Δ={net_delta:.1f})"
                )

        else:  # net_delta < -DELTA_THRESHOLD
            # Too short → buy calls
            qty = min(contracts_needed, self.max_buy_orders_left(self.HEDGE_PRODUCT))
            if qty <= 0:
                return
            best_ask = self.best_ask(self.HEDGE_PRODUCT)
            if best_ask is not None:
                self.send_buy_order(
                    self.HEDGE_PRODUCT, best_ask, qty,
                    msg=f"hedge buy {qty} (Δ={net_delta:.1f})"
                )
            else:
                fair_c = max(round(self._bs_call(S, self.HEDGE_STRIKE, T, self.TARGET_IV)), 1)
                self.send_buy_order(
                    self.HEDGE_PRODUCT, fair_c, qty,
                    msg=f"hedge passive bid {qty} @ {fair_c} (Δ={net_delta:.1f})"
                )

    def _run(self):
        if self.data is None:
            self.data = {
                "starting_prices": {},
            }

        S = self._vfx_mid()
        T = self.tte_()
        self.mm_velvetfruit_extract()
        self.hedge_delta(S, T)
