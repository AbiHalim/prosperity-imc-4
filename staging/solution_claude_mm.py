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
            raise e  ##### RAISE REPLACE FOR FINAL SUBMISSION #####
            # return {}, 0, ""

class RoundThreeTrader(NormalTrader):

    # ---- CONFIGURABLE PARAMETERS ----

    # VFX Market Making
    # Half-spread quoted around fair value (in ticks).
    # Wider = safer against adverse selection but fewer fills.
    VFX_BASE_HALF_SPREAD = 3

    # Scales the realized std dev to produce an additional dynamic spread.
    # Final half-spread = max(BASE, VOL_MULT * std_dev)
    # Wider in volatile conditions → less adverse selection risk.
    VFX_VOL_MULT = 1.0

    # How many ticks to shift our quotes per unit of net inventory.
    # E.g. SKEW=0.05 and position=+100 → both quotes shift down 5 ticks,
    # making our ask cheaper (encourage fills) and bid less attractive.
    VFX_SKEW_PER_UNIT = 0.05

    # EMA decay speed. Higher alpha = faster adaptation to new prices.
    # 0.1 ≈ window of ~10 ticks, 0.2 ≈ ~5 ticks.
    VFX_EMA_ALPHA = 0.15

    VFX_POS_LIMIT = 200

    # HP Market Making
    HP_BASE_HALF_SPREAD = 2
    HP_VOL_MULT = 1.0
    HP_SKEW_PER_UNIT = 0.05
    HP_EMA_ALPHA = 0.15
    HP_POS_LIMIT = 200

    # Options
    TARGET_IV = 0.21         # Historical mean implied vol ≈ 21 %
    IV_BUY_THRESH = 0.195    # Buy when IV implied by market < this
    IV_SELL_THRESH = 0.225   # Sell when IV implied by market > this

    # Time-to-expiry in years for each round (round n → TTE = (7-n+1) days)
    DAYS_PER_YEAR = 252.0
    OPTION_POS_LIMIT = 300
    DEEP_OTM_SELL_LIMIT = 50  # max short in VEV_6000 / VEV_6500

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
            "HYDROGEL_PACK": self.HP_POS_LIMIT
        }


class Trader(RoundThreeTrader):

    # ------------------------------------------------------------------
    # Shared helper: update EMA (fair value) and EMA variance (realized vol)
    # ------------------------------------------------------------------
    def _update_ema_var(self, mid: float, ema_key: str, var_key: str,
                        alpha: float) -> tuple[float, float]:
        """
        Exponentially weighted mean and variance.

        Returns
        -------
        (fair_value, std_dev)
            fair_value  -- EMA of mid price, used as our estimate of fair value
            std_dev     -- sqrt of EMA variance, used to scale the half-spread
        """
        if ema_key not in self.data:
            # Warm-start: use current price as the initial estimate.
            # Variance is seeded with a small positive value to avoid
            # zero-width spreads on the very first tick.
            self.data[ema_key] = mid
            self.data[var_key] = 1.0

        ema = self.data[ema_key]
        var = self.data[var_key]

        new_ema = alpha * mid + (1.0 - alpha) * ema
        dev = mid - new_ema
        new_var = alpha * (dev ** 2) + (1.0 - alpha) * var

        self.data[ema_key] = new_ema
        self.data[var_key] = new_var

        # Floor variance to prevent zero std-dev on perfectly flat prices
        return new_ema, math.sqrt(max(new_var, 0.01))

    # ------------------------------------------------------------------
    # Core market making routine (shared by VFX and HP)
    # ------------------------------------------------------------------
    def _market_make(self, product: str,
                     base_half_spread: float,
                     vol_mult: float,
                     skew_per_unit: float,
                     ema_alpha: float,
                     ema_key: str,
                     var_key: str):
        """
        Market Making with Informed Inventory Skew.

        Each tick we:
          1. Estimate fair value via an EMA of mid price.
          2. Compute a dynamic half-spread = max(base, vol_mult * std_dev).
             Wider spreads protect us when the market is moving fast.
          3. Apply an inventory skew to both quotes:
               skew = -position * skew_per_unit
             - Long inventory → negative skew → lower bid & ask.
               Our ask becomes cheaper (attract buyers), our bid less
               attractive (discourage more buying). Mean-reverts position.
             - Short inventory → positive skew → higher bid & ask.
               Our bid becomes more attractive (attract sellers), our ask
               less attractive. Mean-reverts position.
          4. Place passive bid and ask for remaining capacity.
        """
        best_bid = self.best_bid(product)
        best_ask = self.best_ask(product)

        if best_bid is None or best_ask is None:
            return

        mid = (best_bid + best_ask) / 2.0

        # --- 1. Fair value & realized volatility ---
        fair, std = self._update_ema_var(mid, ema_key, var_key, ema_alpha)

        # --- 2. Dynamic half-spread ---
        half_spread = max(base_half_spread, vol_mult * std)

        # --- 3. Inventory skew ---
        pos = self.position.get(product, 0)
        skew = -pos * skew_per_unit  # negative when long, positive when short

        # --- 4. Quoted prices ---
        # Use floor/ceil so the spread is always at least 2 * half_spread wide.
        our_bid = math.floor(fair - half_spread + skew)
        our_ask = math.ceil(fair + half_spread + skew)

        # Enforce minimum 1-tick gap (should rarely trigger given above)
        if our_ask <= our_bid:
            our_ask = our_bid + 1

        # --- 5. Place orders ---
        buy_qty = self.max_buy_orders_left(product)
        if buy_qty > 0:
            self.send_buy_order(
                product, our_bid, buy_qty,
                f"MM bid={our_bid} fair={fair:.1f} std={std:.2f} pos={pos}"
            )

        sell_qty = self.max_sell_orders_left(product)
        if sell_qty > 0:
            self.send_sell_order(
                product, our_ask, sell_qty,
                f"MM ask={our_ask} fair={fair:.1f} std={std:.2f} pos={pos}"
            )

    # ------------------------------------------------------------------
    # Per-product strategies
    # ------------------------------------------------------------------
    def mm_velvetfruit_extract(self):
        """Market make VELVETFRUIT_EXTRACT with vol-adjusted skewed quotes."""
        self._market_make(
            product="VELVETFRUIT_EXTRACT",
            base_half_spread=self.VFX_BASE_HALF_SPREAD,
            vol_mult=self.VFX_VOL_MULT,
            skew_per_unit=self.VFX_SKEW_PER_UNIT,
            ema_alpha=self.VFX_EMA_ALPHA,
            ema_key="vfx_ema",
            var_key="vfx_var",
        )

    def mm_hydrogel_pack(self):
        """Market make HYDROGEL_PACK with vol-adjusted skewed quotes."""
        self._market_make(
            product="HYDROGEL_PACK",
            base_half_spread=self.HP_BASE_HALF_SPREAD,
            vol_mult=self.HP_VOL_MULT,
            skew_per_unit=self.HP_SKEW_PER_UNIT,
            ema_alpha=self.HP_EMA_ALPHA,
            ema_key="hp_ema",
            var_key="hp_var",
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def _run(self):
        if self.data is None:
            self.data = {}

        # self.mm_velvetfruit_extract()
        self.mm_hydrogel_pack()
