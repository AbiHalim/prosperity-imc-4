import pandas as pd
import numpy as np
import math
import matplotlib.pyplot as plt

def norm_cdf(x):
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    poly = t * (0.319381530 + t * (-0.356563782 +
           t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    pdf = math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
    result = 1.0 - pdf * poly
    return result if x >= 0 else 1.0 - result

def bs_call_price(S, K, T, sigma, r=0.0):
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)

def implied_spot(C, K, T, sigma, r=0.0):
    # Binary search for S
    low, high = 1000, 20000
    for _ in range(50):
        mid = (low + high) / 2
        price = bs_call_price(mid, K, T, sigma, r)
        if price < C:
            low = mid
        else:
            high = mid
    return (low + high) / 2

df = pd.read_csv('data/ROUND_3/prices_round_3_day_0.csv', sep=';')
df['mid_price'] = df['mid_price'].astype(float)

vfx = df[df['product'] == 'VELVETFRUIT_EXTRACT'].set_index('timestamp')
vev_5000 = df[df['product'] == 'VEV_5000'].set_index('timestamp')

merged = vfx[['mid_price']].join(vev_5000[['mid_price']], lsuffix='_vfx', rsuffix='_opt')
merged = merged.dropna()

merged['T'] = (8.0 - merged.index / 10000.0) / 365.0
merged['implied_S'] = [implied_spot(c, 5000, t, 0.24) for c, t in zip(merged['mid_price_opt'], merged['T'])]

merged['diff'] = merged['implied_S'] - merged['mid_price_vfx']

print("Average Diff:", merged['diff'].mean())
print("Corr with future return:", merged['diff'].corr(merged['mid_price_vfx'].shift(-10) - merged['mid_price_vfx']))

plt.plot(merged.index[:1000], merged['mid_price_vfx'][:1000], label='VFX Spot')
plt.plot(merged.index[:1000], merged['implied_S'][:1000], label='Implied Spot from VEV 5000')
plt.legend()
plt.savefig('vfx_implied.png')
