import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def analyze_pairs_trade():
    print("Loading data...")
    days = [0, 1, 2]
    all_hp = []
    all_otm1 = []
    all_otm2 = []
    
    for day in days:
        df = pd.read_csv(f'data/ROUND_3/prices_round_3_day_{day}.csv', sep=';')
        
        hp = df[df['product'] == 'HYDROGEL_PACK'].set_index('timestamp')['mid_price']
        
        # Out of the money calls: 5400 and 5500
        otm1 = df[df['product'] == 'VEV_5400'].set_index('timestamp')['mid_price']
        otm2 = df[df['product'] == 'VEV_5500'].set_index('timestamp')['mid_price']
        
        merged = pd.DataFrame({'HP': hp, 'VEV_5400': otm1, 'VEV_5500': otm2}).dropna()
        
        print(f"Day {day} Correlation (HP vs VEV_5400): {merged['HP'].corr(merged['VEV_5400']):.4f}")
        print(f"Day {day} Correlation (HP vs VEV_5500): {merged['HP'].corr(merged['VEV_5500']):.4f}")
        
        all_hp.append(hp)
        all_otm1.append(otm1)
        all_otm2.append(otm2)

    hp_full = pd.concat(all_hp).reset_index(drop=True)
    otm1_full = pd.concat(all_otm1).reset_index(drop=True)
    otm2_full = pd.concat(all_otm2).reset_index(drop=True)
    
    merged_full = pd.DataFrame({'HP': hp_full, 'VEV_5400': otm1_full, 'VEV_5500': otm2_full}).dropna()
    print(f"\nOverall Correlation (HP vs VEV_5400): {merged_full['HP'].corr(merged_full['VEV_5400']):.4f}")
    print(f"Overall Correlation (HP vs VEV_5500): {merged_full['HP'].corr(merged_full['VEV_5500']):.4f}")

    # Calculate spread ratio using linear regression
    from scipy.stats import linregress
    res = linregress(merged_full['VEV_5400'], merged_full['HP'])
    print(f"\nLinear Regression HP = beta * VEV_5400 + alpha")
    print(f"Beta (Hedge Ratio): {res.slope:.4f}")
    print(f"Alpha: {res.intercept:.4f}")
    print(f"R-squared: {res.rvalue**2:.4f}")

    # Plot
    fig, ax1 = plt.subplots(figsize=(12, 6))
    ax2 = ax1.twinx()
    
    ax1.plot(merged_full.index, merged_full['HP'], 'g-', label='Hydrogel Pack (HP)')
    ax2.plot(merged_full.index, merged_full['VEV_5400'], 'b-', alpha=0.7, label='VEV_5400 (OTM Call)')
    
    ax1.set_xlabel('Timestamp (Ticks across 3 Days)')
    ax1.set_ylabel('HP Price', color='g')
    ax2.set_ylabel('VEV_5400 Price', color='b')
    
    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax2.legend(lines + lines2, labels + labels2, loc=0)
    
    plt.title('Pairs Trading: Hydrogel Pack vs VEV_5400 OTM Call')
    plt.tight_layout()
    plt.savefig('scratch/hp_otm_pairs.png')
    print("\nSaved plot to scratch/hp_otm_pairs.png")

if __name__ == '__main__':
    analyze_pairs_trade()
