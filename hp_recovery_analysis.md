# Hydrogel Pack Recovery Analysis

Copy and paste this script into a cell in your `abi_notebook.ipynb` to analyze exactly how often the price deviates by 14 ticks, how far it usually goes against you after that, and how long it takes to recover.

```python
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# Set style
plt.style.use('dark_background')
sns.set_palette("husl")

# 1. Load Data
dfs = []
for d in [0, 1, 2]:
    try:
        df = pd.read_csv(f'data/ROUND_3/prices_round_3_day_{d}.csv', sep=';')
        df['day'] = d
        dfs.append(df)
    except FileNotFoundError:
        pass

full_df = pd.concat(dfs, ignore_index=True)
hp = full_df[full_df['product'] == 'HYDROGEL_PACK'].copy()
hp['mid_price'] = hp['mid_price'].astype(float)

# --- Configuration ---
FAIR_VALUE = 9991.0
ENTRY_THRESH = 14
EXIT_THRESH = 2

hp['deviation'] = hp['mid_price'] - FAIR_VALUE
hp['abs_dev'] = hp['deviation'].abs()

# 1. Basic Deviation Stats
print("--- Deviation Statistics ---")
mean_dev = hp['abs_dev'].mean()
median_dev = hp['abs_dev'].median()
print(f"Average (Mean) Deviation from {FAIR_VALUE}: {mean_dev:.2f} ticks")
print(f"Median Deviation from {FAIR_VALUE}: {median_dev:.2f} ticks")
print(f"Time spent > {ENTRY_THRESH} ticks away: {(hp['abs_dev'] > ENTRY_THRESH).mean():.2%}")


# 2. Recovery Analysis (Simulation of excursions)
excursions = []
in_trade = False
trade_dir = 0
entry_idx = 0
max_adverse_excursion = 0

mid_prices = hp['mid_price'].values
deviations = hp['deviation'].values

for i in range(len(mid_prices)):
    dev = deviations[i]
    
    if not in_trade:
        if dev >= ENTRY_THRESH:
            in_trade = True
            trade_dir = -1 # we would sell (short)
            entry_idx = i
            max_adverse_excursion = dev
        elif dev <= -ENTRY_THRESH:
            in_trade = True
            trade_dir = 1 # we would buy (long)
            entry_idx = i
            max_adverse_excursion = dev
    else:
        # We are in a trade, track how much worse it gets (Maximum Adverse Excursion)
        if trade_dir == -1:
            max_adverse_excursion = max(max_adverse_excursion, dev)
            # Check if it recovered
            if dev <= EXIT_THRESH:
                excursions.append({
                    'dir': 'Short',
                    'max_dev': max_adverse_excursion,
                    'ticks_held': i - entry_idx,
                    'recovered': True
                })
                in_trade = False
        elif trade_dir == 1:
            max_adverse_excursion = min(max_adverse_excursion, dev)
            # Check if it recovered
            if dev >= -EXIT_THRESH:
                excursions.append({
                    'dir': 'Long',
                    'max_dev': max_adverse_excursion,
                    'ticks_held': i - entry_idx,
                    'recovered': True
                })
                in_trade = False

# Check if the last trade of the data didn't recover before the day ended
if in_trade:
    excursions.append({
        'dir': 'Short' if trade_dir == -1 else 'Long',
        'max_dev': max_adverse_excursion,
        'ticks_held': len(mid_prices) - entry_idx,
        'recovered': False
    })

exc_df = pd.DataFrame(excursions)

print(f"\n--- Excursion & Recovery Analysis (Entry = {ENTRY_THRESH}, Exit = {EXIT_THRESH}) ---")
print(f"Total excursions triggered: {len(exc_df)}")
print(f"Percentage of excursions that successfully recovered: {exc_df['recovered'].mean():.2%}")
print(f"Median ticks held to recover: {exc_df[exc_df['recovered']]['ticks_held'].median():.0f} ticks")
print(f"Max ticks held to recover: {exc_df[exc_df['recovered']]['ticks_held'].max():.0f} ticks")

# Calculate how much further the price went against us AFTER we entered at the threshold
exc_df['adverse_move'] = (exc_df['max_dev'].abs() - ENTRY_THRESH)
print(f"\nMedian adverse move after entry: {exc_df['adverse_move'].median():.1f} additional ticks")
print(f"Max adverse move after entry: {exc_df['adverse_move'].max():.1f} additional ticks")

# 3. Plots
fig, axs = plt.subplots(1, 2, figsize=(15, 5))

sns.histplot(exc_df[exc_df['recovered']]['ticks_held'], bins=50, color='cyan', ax=axs[0])
axs[0].set_title('Time Held Before Recovery')
axs[0].set_xlabel('Ticks')

sns.histplot(exc_df['adverse_move'], bins=50, color='salmon', ax=axs[1])
axs[1].set_title('Maximum Adverse Excursion (Drawdown before recovery)')
axs[1].set_xlabel('Additional Ticks Against Position')

plt.tight_layout()
plt.show()
```
