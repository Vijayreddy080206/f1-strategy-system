import pandas as pd
import numpy as np
import os

# Load the raw data that's already downloaded
df = pd.read_csv('data/processed/all_laps_raw.csv')
print(f"Loaded {len(df)} rows")

# Fix the delta calculation
df = df.sort_values(['Year', 'RoundNumber', 'Driver', 'Stint', 'LapNumber'])

df['BestRaceLap'] = df.groupby(
    ['Year', 'RoundNumber', 'Driver']
)['LapTimeSeconds'].transform('min')

df['LapTimeDelta'] = df['LapTimeSeconds'] - df['BestRaceLap']

# Save fixed training data
model_cols = ['LapTimeDelta', 'TyreLife', 'CompoundEncoded',
              'CircuitEncoded', 'TrackTemp', 'FuelLoad',
              'Year', 'CircuitName', 'Compound']

clean_df = df[model_cols].dropna()
clean_df.to_csv('data/processed/model_training_data.csv', index=False)
print(f"Fixed! Saved {len(clean_df)} rows")
print(f"Sample deltas: {clean_df['LapTimeDelta'].describe()}")