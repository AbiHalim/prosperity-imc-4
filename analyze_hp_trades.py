import pandas as pd
import numpy as np

# Load day 0 data
df = pd.read_csv('data/ROUND_3/trades_round_3_day_0.csv', sep=';')
hp = df[df['symbol'] == 'HYDROGEL_PACK'].copy()

print(f"Total HP trades: {len(hp)}")
print(f"Mean trade quantity: {hp['quantity'].mean():.2f}")
print(f"Median trade quantity: {hp['quantity'].median():.2f}")
print(f"Max trade quantity: {hp['quantity'].max():.2f}")

