import pandas as pd
import numpy as np

# Load day 0 data
df = pd.read_csv('data/ROUND_3/prices_round_3_day_0.csv', sep=';')
hp = df[df['product'] == 'HYDROGEL_PACK'].copy()

hp['mid_price'] = hp['mid_price'].astype(float)
hp['bid_price_1'] = hp['bid_price_1'].astype(float)
hp['ask_price_1'] = hp['ask_price_1'].astype(float)
hp['spread'] = hp['ask_price_1'] - hp['bid_price_1']

print("--- HP Summary ---")
print(f"Mean mid price: {hp['mid_price'].mean():.2f}")
print(f"Min mid price: {hp['mid_price'].min():.2f}")
print(f"Max mid price: {hp['mid_price'].max():.2f}")
print(f"Mean spread: {hp['spread'].mean():.2f}")

hp['mid_change'] = hp['mid_price'].diff()

print("\n--- Autocorrelation ---")
for lag in range(1, 6):
    acf = hp['mid_change'].autocorr(lag=lag)
    print(f"Lag {lag} ACF: {acf:.3f}")

print("\n--- Deviation from 9991 ---")
hp['deviation'] = hp['mid_price'] - 9991
dev_abs = hp['deviation'].abs()
print(f"Time spent > 50 ticks away: {(dev_abs > 50).mean():.2%}")
print(f"Time spent > 20 ticks away: {(dev_abs > 20).mean():.2%}")
print(f"Time spent > 10 ticks away: {(dev_abs > 10).mean():.2%}")

# Mean reversion half-life
print("\n--- Ornstein-Uhlenbeck ---")
y = hp['mid_price'].diff().dropna()
x = hp['mid_price'].shift(1).dropna()
# Regression: dy = a + b * y
model = np.polyfit(x, y, 1)
b, a = model[0], model[1]
if b < 0:
    kappa = -b
    mu = a / kappa
    half_life = np.log(2) / kappa
    print(f"Mean-reverting. Mean: {mu:.2f}")
    print(f"Half-life: {half_life:.1f} ticks")
else:
    print("Not mean-reverting according to OU fit.")

