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

# ---------------------------------------------------------------------------
# Normal distribution CDF approximation (Abramowitz & Stegun)
# ---------------------------------------------------------------------------
def _norm_cdf(x: float) -> float:
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    poly = t * (0.319381530 + t * (-0.356563782 +
           t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    pdf = math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
    result = 1.0 - pdf * poly
    return result if x >= 0 else 1.0 - result


def bs_call_price_and_delta(S: float, K: float, T: float,
                            sigma: float, r: float = 0.0):
    """
    Black-Scholes call price and delta.
    Returns (price, delta). Returns (intrinsic, 1.0 or 0.0) when T<=0.
    """
    if T <= 1e-9 or sigma <= 1e-9:
        intrinsic = max(0.0, S - K)
        return intrinsic, (1.0 if S > K else 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    delta = _norm_cdf(d1)
    return price, delta


class RoundThreeTrader(NormalTrader):

    # ---- CONFIGURABLE PARAMETERS ----

    # Time-to-expiry: 8 days at start of Day 0, decrements 1 day per trading day.
    # Each trading day has 10,000 ticks (timestamps 0..999900, step 100).
    INITIAL_TTE_DAYS = 8.0
    TICKS_PER_DAY    = 10_000.0
    DAYS_PER_YEAR    = 365.0  # fictitious asset — not a 252-day trading calendar

    # Realized volatility estimation (EMA of squared log-returns)
    # Slow alpha → stable estimate; seeded at ATM implied vol (~24% with 365
    # day convention). RV and IV converge at ~800-tick sampling, so no
    # systematic vol premium — arb fires only on tick-level BS deviations.
    DEFAULT_IV  = 0.24
    IV_ALPHA    = 0.02        # EMA speed for realized vol
    IV_MIN      = 0.05        # floor to prevent BS blow-up
    IV_MAX      = 0.60        # cap

    # Option arbitrage: minimum edge (in price ticks) after crossing the
    # bid-ask spread before we trade. Prevents over-trading near noise.
    OPTION_ARBO_THRESH  = 5.0
    OPTION_TRADE_SIZE   = 20  # max units per option order

    # Delta hedge: minimum net portfolio delta (in VFX units) before we hedge.
    DELTA_HEDGE_THRESH  = 5.0

    # HP Market Making
    HP_BASE_HALF_SPREAD = 2
    HP_VOL_MULT         = 1.0
    HP_SKEW_PER_UNIT    = 0.05
    HP_EMA_ALPHA        = 0.15
    HP_POS_LIMIT        = 200

    # Position limits
    VFX_POS_LIMIT    = 200
    OPTION_POS_LIMIT = 300

    # All strikes and their product names
    STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]

    def __init__(self):
        super().__init__()
        self.pos_limits = {
            "VELVETFRUIT_EXTRACT": self.VFX_POS_LIMIT,
            "HYDROGEL_PACK":       self.HP_POS_LIMIT,
        }
        for K in self.STRIKES:
            self.pos_limits[f"VEV_{K}"] = self.OPTION_POS_LIMIT


class Trader(RoundThreeTrader):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _current_tte(self) -> float:
        """
        Returns current time-to-expiry in years.
        We track cumulative ticks elapsed from tick 0 of Day 0.
        TTE = (INITIAL_TTE_DAYS - elapsed_ticks / TICKS_PER_DAY) / DAYS_PER_YEAR
        e.g. Day 0 tick 0 → 8/252, Day 1 tick 0 → 7/252, Day 2 tick 0 → 6/252
        """
        if 'elapsed_ticks' not in self.data:
            self.data['elapsed_ticks'] = 0
        else:
            self.data['elapsed_ticks'] += 1

        remaining_days = self.INITIAL_TTE_DAYS - \
            self.data['elapsed_ticks'] / self.TICKS_PER_DAY
        return max(1e-6, remaining_days / self.DAYS_PER_YEAR)

    def _update_realized_vol(self, S: float) -> float:
        """
        EMA of squared log-returns → annualized realized vol.
        Uses per-tick variance * TICKS_PER_YEAR to annualize.
        """
        ticks_per_year = self.TICKS_PER_DAY * self.DAYS_PER_YEAR
        # Seed: per-tick variance implied by DEFAULT_IV
        init_var = (self.DEFAULT_IV ** 2) / ticks_per_year

        if 'vfx_prev_mid' not in self.data:
            self.data['vfx_prev_mid'] = S
            self.data['rv_var'] = init_var
            return self.DEFAULT_IV

        prev = self.data['vfx_prev_mid']
        if prev > 0:
            log_ret = math.log(S / prev)
            self.data['rv_var'] = (
                self.IV_ALPHA * (log_ret ** 2) +
                (1.0 - self.IV_ALPHA) * self.data['rv_var']
            )
        self.data['vfx_prev_mid'] = S

        ann_vol = math.sqrt(self.data['rv_var'] * ticks_per_year)
        return max(self.IV_MIN, min(self.IV_MAX, ann_vol))

    def _update_ema_var(self, mid: float, ema_key: str, var_key: str,
                        alpha: float):
        """EMA fair value + EMA variance. Returns (fair, std)."""
        if ema_key not in self.data:
            self.data[ema_key] = mid
            self.data[var_key] = 1.0
        ema = self.data[ema_key]
        var = self.data[var_key]
        new_ema = alpha * mid + (1.0 - alpha) * ema
        new_var = alpha * (mid - new_ema) ** 2 + (1.0 - alpha) * var
        self.data[ema_key] = new_ema
        self.data[var_key] = new_var
        return new_ema, math.sqrt(max(new_var, 0.01))

    # ------------------------------------------------------------------
    # Strategy 1: Option Mispricing Arbitrage + Delta Hedge
    # ------------------------------------------------------------------

    def option_arb_and_delta_hedge(self):
        """
        For each VEV_XXXX call option:
          - Compute Black-Scholes theoretical price using current VFX spot,
            remaining TTE, and EMA realized vol.
          - If market ask < BS price - threshold  → BUY (underpriced)
          - If market bid > BS price + threshold  → SELL (overpriced)

        Then delta-hedge the entire options portfolio using VFX:
          net_delta = sum(option_pos_i * delta_i) + vfx_pos
          Trade VFX aggressively to bring net_delta toward 0.
        """
        # --- VFX spot price ---
        vfx_bid = self.best_bid("VELVETFRUIT_EXTRACT")
        vfx_ask = self.best_ask("VELVETFRUIT_EXTRACT")
        if vfx_bid is None or vfx_ask is None:
            return
        S = (vfx_bid + vfx_ask) / 2.0

        # --- Time-to-expiry and realized vol ---
        T     = self._current_tte()
        sigma = self._update_realized_vol(S)

        # --- Option arbitrage pass ---
        total_option_delta = 0.0

        for K in self.STRIKES:
            name = f"VEV_{K}"

            bs_price, bs_delta = bs_call_price_and_delta(S, K, T, sigma)

            # Accumulate existing position delta regardless of market availability
            pos = self.position.get(name, 0)
            total_option_delta += pos * bs_delta

            opt_bid = self.best_bid(name)
            opt_ask = self.best_ask(name)
            if opt_bid is None or opt_ask is None:
                continue

            # BUY if underpriced: we pay opt_ask, theoretical worth bs_price
            edge_buy = bs_price - opt_ask
            if edge_buy > self.OPTION_ARBO_THRESH:
                qty = min(self.OPTION_TRADE_SIZE,
                          self.max_buy_orders_left(name))
                if qty > 0:
                    self.send_buy_order(
                        name, opt_ask, qty,
                        f"ARBO BUY K={K} edge={edge_buy:.1f} "
                        f"bs={bs_price:.1f} mkt_ask={opt_ask}"
                    )
                    total_option_delta += qty * bs_delta  # anticipated fill

            # SELL if overpriced: we receive opt_bid, theoretical worth bs_price
            edge_sell = opt_bid - bs_price
            if edge_sell > self.OPTION_ARBO_THRESH:
                qty = min(self.OPTION_TRADE_SIZE,
                          self.max_sell_orders_left(name))
                if qty > 0:
                    self.send_sell_order(
                        name, opt_bid, qty,
                        f"ARBO SELL K={K} edge={edge_sell:.1f} "
                        f"bs={bs_price:.1f} mkt_bid={opt_bid}"
                    )
                    total_option_delta -= qty * bs_delta  # anticipated fill

        # --- Delta hedge with VFX underlying ---
        # net_delta > 0  → long delta exposure → sell VFX to flatten
        # net_delta < 0  → short delta exposure → buy VFX to flatten
        vfx_pos   = self.position.get("VELVETFRUIT_EXTRACT", 0)
        net_delta = vfx_pos + total_option_delta

        if abs(net_delta) > self.DELTA_HEDGE_THRESH:
            hedge = int(round(-net_delta))  # qty we need to trade in VFX

            if hedge > 0:   # need to BUY VFX
                qty = min(hedge, self.max_buy_orders_left("VELVETFRUIT_EXTRACT"))
                if qty > 0:
                    self.send_buy_order(
                        "VELVETFRUIT_EXTRACT", vfx_ask, qty,
                        f"HEDGE BUY net_delta={net_delta:.1f} sigma={sigma:.3f}"
                    )
            elif hedge < 0: # need to SELL VFX
                qty = min(-hedge, self.max_sell_orders_left("VELVETFRUIT_EXTRACT"))
                if qty > 0:
                    self.send_sell_order(
                        "VELVETFRUIT_EXTRACT", vfx_bid, qty,
                        f"HEDGE SELL net_delta={net_delta:.1f} sigma={sigma:.3f}"
                    )

    # ------------------------------------------------------------------
    # Strategy 2: HP Market Making with Inventory Skew
    # ------------------------------------------------------------------

    def mm_hydrogel_pack(self):
        """
        Market make HYDROGEL_PACK.
        Fair value = EMA of mid price.
        Spread widens with realized vol; quotes skew with inventory.
        """
        best_bid = self.best_bid("HYDROGEL_PACK")
        best_ask = self.best_ask("HYDROGEL_PACK")
        if best_bid is None or best_ask is None:
            return

        mid  = (best_bid + best_ask) / 2.0
        fair, std = self._update_ema_var(
            mid, "hp_ema", "hp_var", self.HP_EMA_ALPHA
        )

        half_spread = max(self.HP_BASE_HALF_SPREAD, self.HP_VOL_MULT * std)
        pos  = self.position.get("HYDROGEL_PACK", 0)
        skew = -pos * self.HP_SKEW_PER_UNIT

        our_bid = math.floor(fair - half_spread + skew)
        our_ask = math.ceil(fair  + half_spread + skew)
        if our_ask <= our_bid:
            our_ask = our_bid + 1

        buy_qty = self.max_buy_orders_left("HYDROGEL_PACK")
        if buy_qty > 0:
            self.send_buy_order(
                "HYDROGEL_PACK", our_bid, buy_qty,
                f"MM bid={our_bid} fair={fair:.1f} pos={pos}"
            )

        sell_qty = self.max_sell_orders_left("HYDROGEL_PACK")
        if sell_qty > 0:
            self.send_sell_order(
                "HYDROGEL_PACK", our_ask, sell_qty,
                f"MM ask={our_ask} fair={fair:.1f} pos={pos}"
            )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def _run(self):
        if self.data is None:
            self.data = {}

        self.option_arb_and_delta_hedge()  # options arb + VFX delta hedge
        self.mm_hydrogel_pack()            # HP market making
