# Hydrogel Pack Analysis

The purpose of this notebook is to analyze the market dynamics of `HYDROGEL_PACK` across multiple days of Round 3 data to verify its mean-reverting properties and confirm the viability of an aggressive mean-reversion market-making strategy anchored to a long-run mean.

```python
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# Set style
plt.style.use('dark_background')
sns.set_palette("husl")

# 1. Load Data
# Load multiple days of Round 3 data to ensure the long-run mean is stable across days
days = [0, 1, 2]
dfs = []
for d in days:
    try:
        df = pd.read_csv(f'data/ROUND_3/prices_round_3_day_{d}.csv', sep=';')
        df['day'] = d
        dfs.append(df)
    except FileNotFoundError:
        print(f"Warning: Day {d} data not found.")

if not dfs:
    raise ValueError("No data files found. Please check paths.")

full_df = pd.concat(dfs, ignore_index=True)
hp = full_df[full_df['product'] == 'HYDROGEL_PACK'].copy()

# Ensure types are correct
hp['mid_price'] = hp['mid_price'].astype(float)
hp['bid_price_1'] = hp['bid_price_1'].astype(float)
hp['ask_price_1'] = hp['ask_price_1'].astype(float)
hp['spread'] = hp['ask_price_1'] - hp['bid_price_1']
hp['timestamp'] = hp['timestamp'] + hp['day'] * 1000000 # Continuous timeline

print(f"Total rows loaded: {len(hp)}")
```

## 1. Long-Run Mean and Spread Analysis

First, we establish if the price is stationary and if the mean holds across different days.

```python
# Basic Statistics
print("--- HP Price Statistics ---")
overall_mean = hp['mid_price'].mean()
print(f"Overall Mean mid price: {overall_mean:.2f}")
print(f"Min mid price: {hp['mid_price'].min():.2f}")
print(f"Max mid price: {hp['mid_price'].max():.2f}")
print(f"Mean spread: {hp['spread'].mean():.2f}")

# Mean per day
print("\n--- Mean per Day ---")
for d in hp['day'].unique():
    day_mean = hp[hp['day'] == d]['mid_price'].mean()
    print(f"Day {d} Mean: {day_mean:.2f}")

# Plot Time Series
plt.figure(figsize=(15, 6))
plt.plot(range(len(hp)), hp['mid_price'], label='Mid Price', alpha=0.8, color='cyan')
plt.axhline(overall_mean, color='red', linestyle='--', label=f'Overall Mean ({overall_mean:.1f})')
plt.title('Hydrogel Pack Mid Price Across Days')
plt.xlabel('Tick Index')
plt.ylabel('Price')
plt.legend()
plt.show()

# Plot Spread Distribution
plt.figure(figsize=(10, 4))
sns.histplot(hp['spread'], bins=30, kde=True, color='purple')
plt.title('Hydrogel Pack Bid-Ask Spread Distribution')
plt.xlabel('Spread (ticks)')
plt.show()
```

## 2. Mean Reversion Properties (Ornstein-Uhlenbeck)

We model the price as an Ornstein-Uhlenbeck process $dy_t = \theta (\mu - y_t)dt + \sigma dW_t$.
By regressing $\Delta y_t$ against $y_{t-1}$, we can find the speed of mean reversion $\theta$ (kappa) and the half-life.

```python
print("--- Ornstein-Uhlenbeck Mean Reversion ---")

# We run this on the continuous series (ignoring the overnight gaps which are tiny anyway)
y = hp['mid_price'].diff().dropna()
x = hp['mid_price'].shift(1).dropna()

# Regression: dy = a + b * y
# Equivalent to: dy = theta * mu - theta * y
model = np.polyfit(x, y, 1)
b, a = model[0], model[1]

if b < 0:
    kappa = -b
    mu = a / kappa
    half_life = np.log(2) / kappa
    print(f"Process is Mean-Reverting.")
    print(f"Implied Mean (mu): {mu:.2f}")
    print(f"Speed of Reversion (kappa): {kappa:.5f} per tick")
    print(f"Half-life: {half_life:.1f} ticks")
else:
    print("Process is NOT mean-reverting (b >= 0).")
```

## 3. Autocorrelation (ACF)

We look at the autocorrelation of price *returns* (changes). A negative lag-1 autocorrelation confirms mean reversion at the micro-structural level.

```python
print("--- Autocorrelation of Price Changes ---")
hp['mid_change'] = hp['mid_price'].diff()

lags = range(1, 11)
acfs = [hp['mid_change'].autocorr(lag=lag) for lag in lags]

for lag, acf in zip(lags[:5], acfs[:5]):
    print(f"Lag {lag} ACF: {acf:.3f}")

plt.figure(figsize=(10, 4))
plt.bar(lags, acfs, color='orange')
plt.axhline(0, color='white', linewidth=0.8)
plt.title('Autocorrelation of Hydrogel Pack Mid Price Changes')
plt.xlabel('Lag (ticks)')
plt.ylabel('ACF')
plt.xticks(lags)
plt.show()
```

## 4. Deviation Analysis (Tail Risk)

To justify our `EXTREME_THRESH = 25` parameter, we need to see how often the price deviates significantly from the true mean. If it happens often, we should fade it.

```python
print("--- Deviation from Mean Analysis ---")
target_mean = 9991.0
hp['deviation'] = hp['mid_price'] - target_mean
hp['abs_deviation'] = hp['deviation'].abs()

thresholds = [10, 20, 25, 30, 40, 50]
for t in thresholds:
    pct = (hp['abs_deviation'] > t).mean()
    print(f"Time spent > {t} ticks away: {pct:.2%}")

plt.figure(figsize=(10, 4))
sns.histplot(hp['deviation'], bins=50, kde=True, color='green')
plt.axvline(25, color='red', linestyle='--', label='+25 Extreme Thresh')
plt.axvline(-25, color='red', linestyle='--', label='-25 Extreme Thresh')
plt.title('Distribution of Price Deviation from 9991')
plt.xlabel('Deviation (ticks)')
plt.legend()
plt.show()
```

## 5. Aggressive Trades Analysis

Finally, we analyze the actual trades that happened in the market to see if there are aggressive bots crossing the spread.

```python
print("--- Market Trade Analysis ---")
trades_dfs = []
for d in days:
    try:
        t_df = pd.read_csv(f'data/ROUND_3/trades_round_3_day_{d}.csv', sep=';', header=0)
        t_df['day'] = d
        trades_dfs.append(t_df)
    except FileNotFoundError:
        pass

if trades_dfs:
    trades_df = pd.concat(trades_dfs, ignore_index=True)
    hp_trades = trades_df[trades_df['symbol'] == 'HYDROGEL_PACK'].copy()
    
    print(f"Total market trades across {len(trades_dfs)} days: {len(hp_trades)}")
    print(f"Average trades per day: {len(hp_trades) / len(trades_dfs):.1f}")
    
    # Exclude our own trades if 'buyer'/'seller' info exists
    if 'buyer' in hp_trades.columns:
        market_only = hp_trades[
            (hp_trades['buyer'] != 'SUBMISSION') & 
            (hp_trades['seller'] != 'SUBMISSION')
        ]
        print(f"Market-only trades (excluding us): {len(market_only)}")
        
        print("\nTrade Quantity Stats:")
        print(f"Mean qty: {market_only['quantity'].mean():.2f}")
        print(f"Median qty: {market_only['quantity'].median():.2f}")
        print(f"Max qty: {market_only['quantity'].max():.2f}")
        
        plt.figure(figsize=(8, 4))
        sns.countplot(x='quantity', data=market_only, palette='viridis')
        plt.title('Distribution of Trade Quantities')
        plt.show()
else:
    print("No trades data found.")
```
