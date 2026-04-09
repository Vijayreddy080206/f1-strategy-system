import fastf1
import pandas as pd
import numpy as np
import os
import time

fastf1.Cache.enable_cache('data/cache')

SEASONS = list(range(2018, 2027))  # 2018 to 2026

def get_lap_time_seconds(lap_time):
    try:
        return lap_time.total_seconds()
    except:
        return np.nan

def load_single_race(year, round_number):
    try:
        session = fastf1.get_session(year, round_number, 'R')
        session.load(telemetry=False, weather=True, messages=False)

        laps = session.laps.copy()

        if laps is None or len(laps) == 0:
            print(f"  SKIPPED {year} Round {round_number}: no lap data")
            return None

        keep_cols = ['Driver', 'LapNumber', 'LapTime', 'Compound',
                     'TyreLife', 'Stint', 'TrackStatus', 'IsAccurate']
        keep_cols = [c for c in keep_cols if c in laps.columns]
        laps = laps[keep_cols].copy()

        laps['LapTimeSeconds'] = laps['LapTime'].apply(get_lap_time_seconds)
        laps['Year'] = year
        laps['RoundNumber'] = round_number
        laps['CircuitName'] = session.event['EventName']

        try:
            weather = session.weather_data
            if weather is not None and len(weather) > 0:
                laps['TrackTemp'] = round(weather['TrackTemp'].mean(), 1)
            else:
                laps['TrackTemp'] = np.nan
        except:
            laps['TrackTemp'] = np.nan

        laps = laps.dropna(subset=['LapTimeSeconds'])

        median_time = laps['LapTimeSeconds'].median()
        laps = laps[laps['LapTimeSeconds'] < median_time * 1.20]

        if 'IsAccurate' in laps.columns:
            laps = laps[laps['IsAccurate'] == True]

        laps = laps[laps['Compound'].isin(['SOFT', 'MEDIUM', 'HARD'])]

        print(f"  Loaded {year} Round {round_number} - {session.event['EventName']} ({len(laps)} laps)")
        return laps

    except Exception as e:
        print(f"  FAILED {year} Round {round_number}: {e}")
        return None


def engineer_features(df):
    # ── Compound encoding ─────────────────────────────────────────────────
    compound_map_enc = {'SOFT': 0, 'MEDIUM': 1, 'HARD': 2}
    df['CompoundEncoded'] = df['Compound'].map(compound_map_enc)

    # ── Circuit encoding — consistent across runs ─────────────────────────
    circuit_map_path = 'data/processed/circuit_map.csv'
    if os.path.exists(circuit_map_path):
        existing = pd.read_csv(circuit_map_path)
        circuit_enc = dict(zip(existing['CircuitName'], existing['CircuitCode']))
        next_code = max(circuit_enc.values()) + 1
        for c in df['CircuitName'].unique():
            if c not in circuit_enc:
                circuit_enc[c] = next_code
                next_code += 1
    else:
        circuits = df['CircuitName'].unique()
        circuit_enc = {c: i for i, c in enumerate(circuits)}

    df['CircuitEncoded'] = df['CircuitName'].map(circuit_enc)

    pd.DataFrame(
        list(circuit_enc.items()),
        columns=['CircuitName', 'CircuitCode']
    ).to_csv(circuit_map_path, index=False)

    # ── Lap time delta from best race lap per driver ───────────────────────
    df = df.sort_values(
        ['Year', 'RoundNumber', 'Driver', 'Stint', 'LapNumber']
    ).copy()

    df['BestRaceLap'] = df.groupby(
        ['Year', 'RoundNumber', 'Driver']
    )['LapTimeSeconds'].transform('min')

    df['LapTimeDelta'] = df['LapTimeSeconds'] - df['BestRaceLap']

    # ── Fuel load estimate ────────────────────────────────────────────────
    df['FuelLoad'] = 100 - (df['LapNumber'] * 1.8)
    df['FuelLoad'] = df['FuelLoad'].clip(lower=0)

    # ── NEW FEATURE 1: Lap time delta from previous lap ───────────────────
    # Detects when tire performance starts dropping lap over lap
    df = df.sort_values(
        ['Year', 'RoundNumber', 'Driver', 'LapNumber']
    ).copy()

    df['LapTimeDelta_prev'] = df.groupby(
        ['Year', 'RoundNumber', 'Driver']
    )['LapTimeSeconds'].diff().fillna(0)

    # Cap extremes — pit laps and SC laps cause huge deltas
    df['LapTimeDelta_prev'] = df['LapTimeDelta_prev'].clip(-5, 5)

    # ── NEW FEATURE 2: Race progress fraction ─────────────────────────────
    # 0.0 = race start, 1.0 = race finish
    # Helps model understand fuel context and stint timing patterns
    max_lap_per_race = df.groupby(
        ['Year', 'RoundNumber']
    )['LapNumber'].transform('max')

    df['RaceProgressFraction'] = df['LapNumber'] / max_lap_per_race

    return df


def load_all_seasons():
    all_laps = []

    for year in SEASONS:
        print(f"\n--- Loading {year} season ---")

        try:
            schedule = fastf1.get_event_schedule(year)
            schedule = schedule[schedule['EventFormat'] != 'testing']
            rounds = schedule['RoundNumber'].tolist()
        except Exception as e:
            print(f"Could not get schedule for {year}: {e}")
            continue

        for round_num in rounds:
            laps = load_single_race(year, round_num)
            if laps is not None and len(laps) > 0:
                all_laps.append(laps)
            time.sleep(60)

    if len(all_laps) == 0:
        print("No data loaded! Check your internet connection.")
        return None

    print("\n--- Combining all data ---")
    full_df = pd.concat(all_laps, ignore_index=True)

    print(f"\nTotal laps collected: {len(full_df)}")
    print(f"Seasons: {sorted(full_df['Year'].unique())}")
    print(f"Circuits: {full_df['CircuitName'].nunique()}")

    print("\n--- Engineering features ---")
    full_df = engineer_features(full_df)

    # ── Save full raw data ────────────────────────────────────────────────
    os.makedirs('data/processed', exist_ok=True)
    full_df.to_csv('data/processed/all_laps_raw.csv', index=False)
    print("Saved: data/processed/all_laps_raw.csv")

    # ── Save clean model training data ───────────────────────────────────
    model_cols = [
        'LapTimeDelta', 'TyreLife', 'CompoundEncoded',
        'CircuitEncoded', 'TrackTemp', 'FuelLoad',
        'LapTimeDelta_prev', 'RaceProgressFraction',
        'Year', 'CircuitName', 'Compound', 'LapNumber'
    ]

    # Only keep columns that exist
    model_cols = [c for c in model_cols if c in full_df.columns]

    clean_df = full_df[model_cols].dropna()
    clean_df.to_csv('data/processed/model_training_data.csv', index=False)
    print(f"Saved: data/processed/model_training_data.csv ({len(clean_df)} rows)")
    print(f"Columns saved: {model_cols}")

    return full_df


if __name__ == "__main__":
    df = load_all_seasons()
    if df is not None:
        print("\nDone! Data pipeline complete.")
        print(df[['Driver', 'LapNumber', 'LapTimeDelta',
                   'LapTimeDelta_prev', 'RaceProgressFraction']].head(10))