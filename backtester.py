import pandas as pd
import numpy as np
from datamodel import Listing, OrderDepth, Trade, TradingState, Order
import importlib.util
import sys
import os
from typing import Dict, List, Any
import collections

# Load Trader from the specified file
def load_trader(path):
    spec = importlib.util.spec_from_file_location("trader_module", path)
    trader_module = importlib.util.module_from_spec(spec)
    sys.modules["trader_module"] = trader_module
    spec.loader.exec_module(trader_module)
    return trader_module.Trader()

class BacktestEngine:
    def __init__(self, trader, prices_df, trades_df):
        self.trader = trader
        self.prices_df = prices_df
        self.trades_df = trades_df
        self.timestamps = sorted(prices_df['timestamp'].unique())
        
        self.cash = 0
        self.positions = collections.defaultdict(int)
        self.own_trades = collections.defaultdict(list)
        self.market_trades = collections.defaultdict(list)
        self.trader_data = ""
        
        # PnL tracking
        self.pnl_history = []
        self.last_mid_prices = {}
        
        # Pending limit orders (passive)
        self.pending_orders = collections.defaultdict(list)

    def run(self):
        print(f"Starting backtest with {len(self.timestamps)} timestamps...")
        
        # Initialize listings
        listings = {}
        for product in self.prices_df['product'].unique():
            listings[product] = Listing(product, product, product)

        for ts in self.timestamps:
            # 1. Prepare Order Depths
            ts_prices = self.prices_df[self.prices_df['timestamp'] == ts]
            order_depths = {}
            current_mid_prices = {}
            
            for _, row in ts_prices.iterrows():
                product = row['product']
                od = OrderDepth()
                for i in range(1, 4):
                    if pd.notna(row[f'bid_price_{i}']):
                        od.buy_orders[int(row[f'bid_price_{i}'])] = int(row[f'bid_volume_{i}'])
                    if pd.notna(row[f'ask_price_{i}']):
                        od.sell_orders[int(row[f'ask_price_{i}'])] = -int(row[f'ask_volume_{i}'])
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

            # 3. Fill Pending Passive Orders based on Market Trades
            # A passive buy fills if a market trade happens at or below the buy price.
            # A passive sell fills if a market trade happens at or above the sell price.
            for product, trades in market_trades_this_tick.items():
                if product not in self.pending_orders: continue
                
                still_pending = []
                for order in self.pending_orders[product]:
                    filled = False
                    for t in trades:
                        if order.quantity > 0: # Passive Buy
                            if t.price <= order.price:
                                fill_qty = order.quantity # Assume full fill for simplicity
                                self.positions[product] += fill_qty
                                self.cash -= fill_qty * t.price
                                self.own_trades[product].append(Trade(product, t.price, fill_qty, timestamp=ts))
                                filled = True
                                break
                        else: # Passive Sell
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

            # 4. Construct TradingState
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
            
            # Reset own trades for next tick
            self.own_trades = collections.defaultdict(list)

            # 6. Process New Orders
            # Clear old pending orders? Prosperity usually cancels un-filled limit orders each tick.
            self.pending_orders = collections.defaultdict(list)

            for product, orders in orders_to_send.items():
                od = order_depths.get(product)
                if not od: continue
                
                for order in orders:
                    quantity = order.quantity
                    price = order.price
                    
                    if quantity > 0: # Buy order
                        # Match against sell orders (asks)
                        sorted_asks = sorted(od.sell_orders.items())
                        for ask_price, ask_vol in sorted_asks:
                            if ask_price <= price and quantity > 0:
                                fill_qty = min(quantity, abs(ask_vol))
                                self.positions[product] += fill_qty
                                self.cash -= fill_qty * ask_price
                                quantity -= fill_qty
                                od.sell_orders[ask_price] += fill_qty
                                if od.sell_orders[ask_price] == 0:
                                    del od.sell_orders[ask_price]
                                
                                self.own_trades[product].append(Trade(product, ask_price, fill_qty, timestamp=ts))
                            else:
                                break
                        # If still quantity left, it's a passive order
                        if quantity > 0:
                            self.pending_orders[product].append(Order(product, price, quantity))

                    elif quantity < 0: # Sell order
                        quantity = abs(quantity)
                        sorted_bids = sorted(od.buy_orders.items(), reverse=True)
                        for bid_price, bid_vol in sorted_bids:
                            if bid_price >= price and quantity > 0:
                                fill_qty = min(quantity, bid_vol)
                                self.positions[product] -= fill_qty
                                self.cash += fill_qty * bid_price
                                quantity -= fill_qty
                                od.buy_orders[bid_price] -= fill_qty
                                if od.buy_orders[bid_price] == 0:
                                    del od.buy_orders[bid_price]
                                
                                self.own_trades[product].append(Trade(product, bid_price, -fill_qty, timestamp=ts))
                            else:
                                break
                        # Passive sell
                        if quantity > 0:
                            self.pending_orders[product].append(Order(product, price, -quantity))

            # 6. Calculate Unrealized PnL
            unrealized_pnl = 0
            for product, pos in self.positions.items():
                if product in current_mid_prices:
                    unrealized_pnl += pos * current_mid_prices[product]
            
            total_pnl = self.cash + unrealized_pnl
            if ts % 10000 == 0:
                print(f"Timestamp {ts}: Cash={self.cash:.2f}, PnL={total_pnl:.2f}, Positions={dict(self.positions)}")
            
            self.pnl_history.append({'timestamp': ts, 'pnl': total_pnl})
            self.last_mid_prices = current_mid_prices

        # Final Liquidation at mid-price
        print("\n--- FINAL LIQUIDATION ---")
        final_pnl = self.cash
        for product, pos in self.positions.items():
            if pos != 0:
                mid = self.last_mid_prices.get(product, 0)
                liquidation_value = pos * mid
                print(f"Liquidating {pos} of {product} at {mid} -> {liquidation_value:.2f}")
                final_pnl += liquidation_value
        
        print(f"Final Total PnL: {final_pnl:.2f}")
        return final_pnl

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Prosperity Backtester")
    parser.add_argument("--day", type=int, default=0, help="Day to backtest (-1, 0, 1)")
    parser.add_argument("--all", action="store_true", help="Run backtest on all available days")
    args = parser.parse_args()

    trader_path = "versions/round_1/FINAL.py"
    
    days = [-1, 0, 1] if args.all else [args.day]
    
    total_pnl_all_days = 0
    
    for day in days:
        print(f"\n{'='*20}")
        print(f"  BACKTESTING DAY {day}")
        print(f"{'='*20}")
        
        prices_path = f"data/ROUND_2/prices_round_2_day_{day}.csv"
        trades_path = f"data/ROUND_2/trades_round_2_day_{day}.csv"
        
        if not os.path.exists(prices_path) or not os.path.exists(trades_path):
            print(f"Files for day {day} not found, skipping...")
            continue
            
        prices_df = pd.read_csv(prices_path, sep=';')
        trades_df = pd.read_csv(trades_path, sep=';')
        trades_df = trades_df.set_index('timestamp')
        
        trader = load_trader(trader_path)
        engine = BacktestEngine(trader, prices_df, trades_df)
        day_pnl = engine.run()
        total_pnl_all_days += day_pnl

    print(f"\n{'='*30}")
    print(f"OVERALL TOTAL PNL: {total_pnl_all_days:.2f}")
    print(f"{'='*30}")

if __name__ == "__main__":
    main()
