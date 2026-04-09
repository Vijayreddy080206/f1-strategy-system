import pandas as pd
import numpy as np
import os
import joblib
import json
from lifelines import WeibullAFTFitter
import warnings

# Suppress lifelines convergence warnings
warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DATA_PATH = os.path.join(BASE_DIR, 'data', 'processed', 'all_laps_raw.csv')
SAVE_DIR = os.path.join(BASE_DIR, 'models', 'survival')

def prepare_survival_data():
    print("=" * 60)
    print("1. PREPARING DATA (WEIBULL EXPONENTIAL WEAR & CENSOR FIX)")
    print("=" * 60)
    
    if not os.path.exists(RAW_DATA_PATH):
        raise FileNotFoundError(f"Cannot find data at {RAW_DATA_PATH}.")
        
    df = pd.read_csv(RAW_DATA_PATH)
    print(f"Loaded {len(df):,} raw laps.")
    
    df = df.dropna(subset=['LapTimeSeconds', 'Compound', 'TyreLife'])
    df = df[df['Compound'].isin(['SOFT', 'MEDIUM', 'HARD'])]
    
    df['BestRaceLap'] = df.groupby(['Year', 'RoundNumber', 'Driver'])['LapTimeSeconds'].transform('min')
    df['LapTimeDelta'] = df['LapTimeSeconds'] - df['BestRaceLap']
    
    # FILTER 1: Massive anomalies (Pit stops, VSC)
    df = df[df['LapTimeDelta'] < 8.0].copy()
    
    # Fuel correction
    df['FuelCorrectedDelta'] = df['LapTimeDelta'] - ((100 - (df['LapNumber'] * 1.8)) * 0.030 / 100)
    df['FuelCorrectedDelta'] = df['FuelCorrectedDelta'].clip(lower=0)
    
    stints = []
    grouped = df.groupby(['Year', 'RoundNumber', 'Driver', 'Stint'])
    CLIFF_THRESHOLD_SECONDS = 2.0
    
    # Industry baseline cliffs to catch "Informative Censoring"
    EXPECTED_CLIFF = {'SOFT': 18, 'MEDIUM': 28, 'HARD': 38}
    
    for name, group in grouped:
        group = group.sort_values('TyreLife').copy()
        if len(group) < 5:
            continue 
            
        max_life = group['TyreLife'].max()
        compound = group['Compound'].iloc[0]
        track_temp = group['TrackTemp'].mean()
        circuit_enc = group['CircuitEncoded'].iloc[0]
        
        # 3-lap rolling median to ignore single-lap lockups
        group['SmoothedDelta'] = group['FuelCorrectedDelta'].rolling(window=3, min_periods=1).median()
        cliff_laps = group[group['SmoothedDelta'] >= CLIFF_THRESHOLD_SECONDS]
        
        if len(cliff_laps) > 0:
            cliff_lap = cliff_laps['TyreLife'].min()
            
            # Anomaly filter: Did a hard tire "die" on lap 8? That's damage, censor it.
            if cliff_lap < (EXPECTED_CLIFF[compound] * 0.4):
                event = 0 
                duration = max_life
            else:
                event = 1 # True tire cliff observed
                duration = cliff_lap
        else:
            # INFORMATIVE CENSORING FIX:
            # If they pitted, but the tire was > 85% through its expected life, 
            # they pitted to avoid the cliff. We mathematically treat this as a tire death.
            if max_life >= (EXPECTED_CLIFF[compound] * 0.85):
                event = 1 
                duration = max_life
            else:
                event = 0 # Truly censored (early strategic stop due to SC, etc.)
                duration = max_life
            
        # Weibull models require strictly positive durations (> 0)
        if duration > 0:
            stints.append({
                'Duration': duration,
                'Event': event,
                'Compound': compound,
                'TrackTemp': track_temp,
                'CircuitEncoded': circuit_enc
            })

    survival_df = pd.DataFrame(stints).dropna()
    survival_df = pd.get_dummies(survival_df, columns=['Compound'], drop_first=False)
    survival_df.columns = [c.replace(' ', '_').replace('-', '_') for c in survival_df.columns]
    
    events = survival_df['Event'].sum()
    print(f"Processed into {len(survival_df):,} clean tire stints.")
    print(f"Detected {events:,} true cliffs + strategic cliff avoidances ({(events/len(survival_df))*100:.1f}%).")
    
    return survival_df

def train_survival_model(survival_df):
    print("\n" + "=" * 60)
    print("2. TRAINING WEIBULL AFT MODEL (EXPONENTIAL FATIGUE)")
    print("=" * 60)
    
    # Switch to Weibull Accelerated Failure Time model for exponential tire wear
    aft = WeibullAFTFitter(penalizer=0.1)
    aft.fit(survival_df, duration_col='Duration', event_col='Event', show_progress=True)
    
    os.makedirs(SAVE_DIR, exist_ok=True)
    model_path = os.path.join(SAVE_DIR, 'weibull_survival_model.pkl')
    joblib.dump(aft, model_path)
    
    features = list(survival_df.drop(columns=['Duration', 'Event']).columns)
    config = {'features': features, 'cliff_threshold_seconds': 2.0, 'model_type': 'weibull'}
    with open(os.path.join(SAVE_DIR, 'survival_config.json'), 'w') as f:
        json.dump(config, f, indent=2)
        
    print(f"\n✅ Weibull Survival Model saved to {model_path}")
    return aft, features

def test_inference(aft, features):
    print("\n" + "=" * 60)
    print("3. TESTING SURVIVAL INFERENCE (RACE WALL OUTPUT)")
    print("=" * 60)
    
    test_data = pd.DataFrame([{f: 0 for f in features} for _ in range(3)])
    test_data['TrackTemp'] = 35.0
    test_data['CircuitEncoded'] = 1.0
    
    if 'Compound_SOFT' in features: test_data.loc[0, 'Compound_SOFT'] = 1
    if 'Compound_MEDIUM' in features: test_data.loc[1, 'Compound_MEDIUM'] = 1
    if 'Compound_HARD' in features: test_data.loc[2, 'Compound_HARD'] = 1
    
    print("Predicting probability of tire SURVIVAL at specific laps:\n")
    print(f"{'Lap':>4} | {'Soft':>12} | {'Medium':>12} | {'Hard':>12}")
    print("-" * 52)
    
    survival_curves = aft.predict_survival_function(test_data)
    
    for lap in [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]:
        closest_lap = survival_curves.index[survival_curves.index <= lap].max()
        if pd.isna(closest_lap):
            closest_lap = survival_curves.index.min()
            
        probs = survival_curves.loc[closest_lap].values
        soft_prob = f"{probs[0]*100:.1f}%"
        med_prob = f"{probs[1]*100:.1f}%" if len(probs) > 1 else "N/A"
        hard_prob = f"{probs[2]*100:.1f}%" if len(probs) > 2 else "N/A"
        
        print(f"{lap:>4} | {soft_prob:>12} | {med_prob:>12} | {hard_prob:>12}")

if __name__ == "__main__":
    df = prepare_survival_data()
    model, feature_list = train_survival_model(df)
    test_inference(model, feature_list)