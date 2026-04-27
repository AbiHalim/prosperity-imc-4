import pandas as pd
import numpy as np

df = pd.read_csv('data/ROUND_3/prices_round_3_day_2.csv', sep=';')
hp = df[df['product'] == 'HYDROGEL_PACK'].copy()
hp['mid'] = hp['mid_price'].astype(float)
FAIR = 9991.0
hp['deviation'] = hp['mid'] - FAIR
hp['mr_skew'] = -hp['deviation'] * 0.5
hp['bid'] = np.floor(FAIR - 3 + hp['mr_skew'])
hp['ask'] = np.ceil(FAIR + 3 + hp['mr_skew'])

print(hp[['timestamp', 'mid', 'deviation', 'mr_skew']].head())
