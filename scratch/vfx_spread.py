import pandas as pd
df = pd.read_csv('data/ROUND_3/prices_round_3_day_0.csv', sep=';')
vfx = df[df['product'] == 'VELVETFRUIT_EXTRACT']
print("VFX Mean Spread:", (vfx['ask_price_1'] - vfx['bid_price_1']).mean())
print("VFX Median Spread:", (vfx['ask_price_1'] - vfx['bid_price_1']).median())
