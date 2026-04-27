import pandas as pd
import numpy as np
import math

def norm_cdf(x):
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    poly = t * (0.319381530 + t * (-0.356563782 +
           t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    pdf = math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
    result = 1.0 - pdf * poly
    return result if x >= 0 else 1.0 - result

def bs_call_price_and_delta(S, K, T, sigma, r=0.0):
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K), (1.0 if S > K else 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    price = S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    delta = norm_cdf(d1)
    return price, delta

df = pd.read_csv('data/ROUND_3/prices_round_3_day_0.csv', sep=';')
df['mid_price'] = df['mid_price'].astype(float)

vfx = df[df['product'] == 'VELVETFRUIT_EXTRACT'].set_index('timestamp')
vev_5000 = df[df['product'] == 'VEV_5000'].set_index('timestamp')

merged = vfx[['mid_price']].join(vev_5000[['mid_price']], lsuffix='_vfx', rsuffix='_opt')
merged = merged.dropna()
merged['T'] = (8.0 - merged.index / 10000.0) / 365.0

approx_S = []
for S, C_mkt, T in zip(merged['mid_price_vfx'], merged['mid_price_opt'], merged['T']):
    C_bs, delta = bs_call_price_and_delta(S, 5000, T, 0.24)
    # Approximation
    if delta > 0.05:
        implied_S = S + (C_mkt - C_bs) / delta
    else:
        implied_S = S
    approx_S.append(implied_S)

merged['implied_S_approx'] = approx_S
merged['diff_approx'] = merged['implied_S_approx'] - merged['mid_price_vfx']

print("Average Diff (Approx):", merged['diff_approx'].mean())
print("Corr with future 10-tick return (Approx):", merged['diff_approx'].corr(merged['mid_price_vfx'].shift(-10) - merged['mid_price_vfx']))
