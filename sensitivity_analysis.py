import pandas as pd
import numpy as np
import collections
import random
import os
from backtester import BacktestEngine, load_trader
from datamodel import Listing, OrderDepth, Trade, TradingState, Order

class SensitivityEngine(BacktestEngine):
    def __init__(self, trader, prices_df, trades_df, visibility=0.8, seed=42):
        super().__init__(trader, prices_df, trades_df)
        self.visibility = visibility
        random.seed(seed)
        self.log_prefix = f"[Visibility {visibility*100:.0f}%]"

    def run(self, silent=False):
        if not silent:
            print(f"{self.log_prefix} Starting backtest...")
        
        listings = {}
        for product in self.prices_df['product'].unique():
            listings[product] = Listing(product, product, product)

        for ts in self.timestamps:
            # 1. Prepare Order Depths with Reduced Visibility
            ts_prices = self.prices_df[self.prices_df['timestamp'] == ts]
            order_depths = {}
            current_mid_prices = {}
            
            for _, row in ts_prices.iterrows():
                product = row['product']
                od = OrderDepth()
                
                # Bids
                for i in range(1, 4):
                    price_key = f'bid_price_{i}'
                    vol_key = f'bid_volume_{i}'
                    if pd.notna(row[price_key]):
                        # Randomly decide to keep this order level based on visibility
                        if random.random() < self.visibility:
                            od.buy_orders[int(row[price_key])] = int(row[vol_key])
                
                # Asks
                for i in range(1, 4):
                    price_key = f'ask_price_{i}'
                    vol_key = f'ask_volume_{i}'
                    if pd.notna(row[price_key]):
                        if random.random() < self.visibility:
                            od.sell_orders[int(row[price_key])] = -int(row[vol_key])
                
                order_depths[product] = od
                current_mid_prices[product] = row['mid_price']

            # 2. Prepare Market Trades
            prev_ts = ts - 100
            market_trades_this_tick = collections.defaultdict(list)
            if prev_ts in self.trades_df.index:
                ts_trades = self.trades_df.loc[prev_ts]
                if isinstance(ts_trades, pd.Series):
                    ts_trades = [ts_trades]
                else:
                    ts_trades = ts_trades.to_dict('records')
                
                for t in ts_trades:
                    market_trades_this_tick[t['symbol']].append(Trade(t['symbol'], t['price'], t['quantity'], timestamp=prev_ts))

            # 3. Passive Order Fills
            for product, trades in market_trades_this_tick.items():
                if product not in self.pending_orders: continue
                still_pending = []
                for order in self.pending_orders[product]:
                    filled = False
                    for t in trades:
                        if order.quantity > 0:
                            if t.price <= order.price:
                                fill_qty = order.quantity
                                self.positions[product] += fill_qty
                                self.cash -= fill_qty * t.price
                                self.own_trades[product].append(Trade(product, t.price, fill_qty, timestamp=ts))
                                filled = True
                                break
                        else:
                            if t.price >= order.price:
                                fill_qty = abs(order.quantity)
                                self.positions[product] -= fill_qty
                                self.cash += fill_qty * t.price
                                self.own_trades[product].append(Trade(product, t.price, -fill_qty, timestamp=ts))
                                filled = True
                                break
                    if not filled:
                        still_pending.append(order)
                self.pending_orders[product] = still_pending

            # 4. Trading State
            state = TradingState(
                traderData=self.trader_data,
                timestamp=ts,
                listings=listings,
                order_depths=order_depths,
                own_trades=self.own_trades,
                market_trades=market_trades_this_tick,
                position=dict(self.positions),
                observations=None
            )

            # 5. Run Trader
            orders_to_send, conversions, next_trader_data = self.trader.run(state)
            self.trader_data = next_trader_data
            self.own_trades = collections.defaultdict(list)
            self.pending_orders = collections.defaultdict(list)

            # 6. Process New Orders (Matching against current depth)
            for product, orders in orders_to_send.items():
                od = order_depths.get(product)
                if not od: continue
                for order in orders:
                    quantity = order.quantity
                    price = order.price
                    if quantity > 0:
                        sorted_asks = sorted(od.sell_orders.items())
                        for ask_price, ask_vol in sorted_asks:
                            if ask_price <= price and quantity > 0:
                                fill_qty = min(quantity, abs(ask_vol))
                                self.positions[product] += fill_qty
                                self.cash -= fill_qty * ask_price
                                quantity -= fill_qty
                                od.sell_orders[ask_price] += fill_qty
                                if od.sell_orders[ask_price] == 0: del od.sell_orders[ask_price]
                                self.own_trades[product].append(Trade(product, ask_price, fill_qty, timestamp=ts))
                            else: break
                        if quantity > 0: self.pending_orders[product].append(Order(product, price, quantity))
                    elif quantity < 0:
                        quantity = abs(quantity)
                        sorted_bids = sorted(od.buy_orders.items(), reverse=True)
                        for bid_price, bid_vol in sorted_bids:
                            if bid_price >= price and quantity > 0:
                                fill_qty = min(quantity, bid_vol)
                                self.positions[product] -= fill_qty
                                self.cash += fill_qty * bid_price
                                quantity -= fill_qty
                                od.buy_orders[bid_price] -= fill_qty
                                if od.buy_orders[bid_price] == 0: del od.buy_orders[bid_price]
                                self.own_trades[product].append(Trade(product, bid_price, -fill_qty, timestamp=ts))
                            else: break
                        if quantity > 0: self.pending_orders[product].append(Order(product, price, -quantity))

            # PnL
            unrealized_pnl = 0
            for product, pos in self.positions.items():
                if product in current_mid_prices:
                    unrealized_pnl += pos * current_mid_prices[product]
            total_pnl = self.cash + unrealized_pnl
            self.pnl_history.append({'timestamp': ts, 'pnl': total_pnl})
            self.last_mid_prices = current_mid_prices

        # Final Liquidation
        final_pnl = self.cash
        for product, pos in self.positions.items():
            if pos != 0:
                mid = self.last_mid_prices.get(product, 0)
                final_pnl += pos * mid
        
        return final_pnl

def main():
    ROUND = 2
    days = [-1, 0, 1]
    for day in days:
        trader_path = "versions/round_1/FINAL.py"
        prices_path = f"data/ROUND_{ROUND}/prices_round_{ROUND}_day_{day}.csv"
        trades_path = f"data/ROUND_{ROUND}/trades_round_{ROUND}_day_{day}.csv"
        
        prices_df = pd.read_csv(prices_path, sep=';')
        trades_df = pd.read_csv(trades_path, sep=';')
        trades_df = trades_df.set_index('timestamp')
        
        print(f"Comparison for Day {day}:")
        
        # 1. 100% Visibility
        trader_100 = load_trader(trader_path)
        engine_100 = SensitivityEngine(trader_100, prices_df, trades_df, visibility=1.0)
        pnl_100 = engine_100.run()
        
        # 2. 80% Visibility
        trader_80 = load_trader(trader_path)
        engine_80 = SensitivityEngine(trader_80, prices_df, trades_df, visibility=0.8)
        pnl_80 = engine_80.run()
        
        print("\n" + "="*40)
        print(f"{'Metric':<20} | {'100% Visibility':<15} | {'80% Visibility':<15}")
        print("-" * 56)
        print(f"{'Total PnL':<20} | {pnl_100:>15.2f} | {pnl_80:>15.2f}")
        print(f"{'Impact':<20} | {'-':>15} | {pnl_80 - pnl_100:>+15.2f} ({((pnl_80/pnl_100)-1)*100:>+5.2f}%)")
        print("="*40)

if __name__ == "__main__":
    main()
