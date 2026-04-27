import pandas as pd
import numpy as np

# Load day 0 data
df = pd.read_csv('data/ROUND_3/trades_round_3_day_0.csv', sep=';', header=0)
print(df.columns)
if 'buyer' in df.columns and 'seller' in df.columns:
    hp = df[df['symbol'] == 'HYDROGEL_PACK'].copy()
    hp['our_trade'] = (hp['buyer'] == 'SUBMISSION') | (hp['seller'] == 'SUBMISSION')
    print("Market trades:")
    print(hp[~hp['our_trade']].head())
