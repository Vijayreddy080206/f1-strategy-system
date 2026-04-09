import pandas as pd
import numpy as np
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
import joblib
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

df = pd.read_csv(os.path.join(BASE_DIR, 'data', 'processed', 'model_training_data.csv'))
print(f"Loaded {len(df)} rows")

# ==============================================================================
# SURGICAL ML DATA FIX
# ==============================================================================
before = len(df)

# 1. Kill Out-Laps & Opening Laps
df = df[df['TyreLife'] >= 3]
if 'LapNumber' in df.columns:
    df = df[df['LapNumber'] >= 5]

# 2. Fuel Correction: To isolate tire deg, we ADD the fuel advantage back.
FUEL_BURN_ADVANTAGE = 0.065
if 'LapNumber' in df.columns and 'LapTimeDelta' in df.columns:
    df['LapTimeDelta'] = df['LapTimeDelta'] + (df['LapNumber'] * FUEL_BURN_ADVANTAGE)

# 3. Clean Outliers
df = df[(df['LapTimeDelta'] >= 0.0) & (df['LapTimeDelta'] <= 12.0)]
TARGET = 'LapTimeDelta'

print(f"Applied Fuel Correction. Removed {before - len(df)} noisy/outlier rows. Clean: {len(df)}")

# ==============================================================================
# STRICT PHYSICS FEATURES (Removed cheating features like LapTimeDelta_prev)
# ==============================================================================
CANDIDATE_FEATURES = ['TyreLife', 'CompoundEncoded', 'CircuitEncoded', 'TrackTemp']
FEATURES = [f for f in CANDIDATE_FEATURES if f in df.columns]
print(f"Strict Physics Features: {FEATURES}")

df_clean = df[FEATURES + [TARGET, 'Year', 'CircuitName', 'Compound']].dropna()

# 80/20 random split
df_train, df_test = train_test_split(df_clean, test_size=0.2, random_state=42)
X_train, y_train  = df_train[FEATURES], df_train[TARGET]
X_test,  y_test   = df_test[FEATURES],  df_test[TARGET]

# Train
model = XGBRegressor(
    n_estimators=800, max_depth=5, learning_rate=0.03, subsample=0.8,
    colsample_bytree=0.8, min_child_weight=10, reg_alpha=0.5, reg_lambda=2.0,
    early_stopping_rounds=50, random_state=42, n_jobs=-1
)

print("\nTraining Pure Physics Model...")
model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=0)

preds = model.predict(X_test)
mae   = mean_absolute_error(y_test, preds)
r2    = r2_score(y_test, preds)
print(f"✅ MAE: {mae:.3f}s  |  R²: {r2:.3f}")

# Feature Importance
importance = pd.DataFrame({
    'feature':    FEATURES,
    'importance': model.feature_importances_
}).sort_values('importance', ascending=False)
print("\nFeature Importance:")
print(importance.to_string(index=False))

# Save
save_dir = os.path.join(BASE_DIR, 'models', 'degradation')
os.makedirs(save_dir, exist_ok=True)
joblib.dump(model, os.path.join(save_dir, 'xgb_model.pkl'))

config = {
    'fuel_effect_per_lap': FUEL_BURN_ADVANTAGE,
    'features': FEATURES,
    'target': TARGET,
    'mae': round(mae, 4), 'r2': round(r2, 4)
}
with open(os.path.join(save_dir, 'model_config.json'), 'w') as f:
    json.dump(config, f, indent=2)
print("✅ Model and config saved")

# ==============================================================================
# SANITY CHECK: DEGRADATION CURVES
# ==============================================================================
circuit_map_path = os.path.join(BASE_DIR, 'data', 'processed', 'circuit_map.csv')
if os.path.exists(circuit_map_path):
    circuit_map  = pd.read_csv(circuit_map_path)
    bahrain      = circuit_map[circuit_map['CircuitName'].str.contains('Bahrain', case=False)]
    circuit_code = int(bahrain['CircuitCode'].values[0]) if len(bahrain) > 0 else 0
    circuit_name = bahrain['CircuitName'].values[0] if len(bahrain) > 0 else 'Circuit 0'

    print(f"\n📊 Degradation curves at {circuit_name} (35°C):")
    print(f"{'Lap':>4} | {'Soft':>8} | {'Medium':>8} | {'Hard':>8}")
    print("-" * 42)

    for lap in [3, 5, 8, 10, 13, 15, 18, 20, 23, 25, 28, 30, 33, 35, 38, 40]:
        row_str = f"{lap:>4} |"
        for cname, ccode in [('Soft', 0), ('Medium', 1), ('Hard', 2)]:
            sample = {f: 0.0 for f in FEATURES}
            if 'TyreLife' in FEATURES: sample['TyreLife'] = float(lap)
            if 'CompoundEncoded' in FEATURES: sample['CompoundEncoded'] = float(ccode)
            if 'CircuitEncoded' in FEATURES: sample['CircuitEncoded']  = float(circuit_code)
            if 'TrackTemp' in FEATURES: sample['TrackTemp']       = 35.0
            
            s     = pd.DataFrame([sample])
            delta = max(0, float(model.predict(s)[0]))
            row_str += f" {delta:>+7.3f}s |"
        print(row_str)

    print("\nIdeal pattern: numbers RISE as lap increases")
    print("Soft lowest early, highest late. Hard highest early, lowest late.")