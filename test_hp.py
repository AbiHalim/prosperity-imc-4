import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv('data/ROUND_3/prices_round_3_day_2.csv', sep=';')
hp = df[df['product'] == 'HYDROGEL_PACK'].copy()
hp['mid_price'] = hp['mid_price'].astype(float)
print("Day 2 Mean:", hp['mid_price'].mean())

df1 = pd.read_csv('data/ROUND_3/prices_round_3_day_1.csv', sep=';')
hp1 = df1[df1['product'] == 'HYDROGEL_PACK'].copy()
hp1['mid_price'] = hp1['mid_price'].astype(float)
print("Day 1 Mean:", hp1['mid_price'].mean())
