import fastf1
import redis
import time
import json
import argparse
import sys
import os
import math

# ==============================================================================
# ARGUMENT PARSING (Listens to the App Manager's button clicks)
# ==============================================================================
parser = argparse.ArgumentParser()
parser.add_argument('--year', type=int, default=2026)
parser.add_argument('--track', type=str, default='Chaina')
args = parser.parse_args()

# ==============================================================================
# REDIS CONNECTION
# ==============================================================================
try:
    r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    r.ping()
    print("✅ Replay Feed connected to Redis!")
except Exception as e:
    print("❌ Redis connection failed:", e)
    sys.exit()

# ==============================================================================
# FASTF1 DATA LOADING
# ==============================================================================
os.makedirs('data_cache', exist_ok=True)
fastf1.Cache.enable_cache('data_cache')

print(f"📥 Downloading/Loading F1 Data: {args.year} {args.track}...")
print("⏳ (This may take 30-60 seconds if not cached)")

try:
    session = fastf1.get_session(args.year, args.track, 'R')
    # telemetry=False speeds up loading massively since we only need lap strategy data
    session.load(telemetry=False, weather=True) 
    print("🚀 Data loaded! Beginning playback simulation...")
except Exception as e:
    print(f"❌ Failed to load session data: {e}")
    sys.exit()

# ==============================================================================
# THE REPLAY ENGINE (Simulates live streaming)
# ==============================================================================
total_laps = session.total_laps
laps = session.laps

# Simulate the race lap by lap
for current_lap in range(1, total_laps + 1):
    lap_data = laps[laps['LapNumber'] == current_lap]
    
    if lap_data.empty:
        continue

    race_state = {
        "track_name": args.track,
        "total_laps": total_laps,
        "lap_number": current_lap,
        "track_moisture": 0.0, 
        "is_sc_active": False,
        "sc_probabilities": {"Q1": 15, "Q2": 20, "Q3": 45, "Q4": 10},
        "drivers": {}
    }

    # Sort drivers by lap completion time to figure out the exact running order
    lap_data_sorted = lap_data.sort_values(by='Time')
    
    if lap_data_sorted.empty:
        continue
        
    leader_time = lap_data_sorted.iloc[0]['Time']
    prev_driver_time = leader_time
    position = 1
    
    for index, row in lap_data_sorted.iterrows():
        tla = row['Driver']
        
        # Calculate live gaps
        gap_to_leader = (row['Time'] - leader_time).total_seconds()
        gap_ahead = (row['Time'] - prev_driver_time).total_seconds()
        
        # Safely extract compound and age (FastF1 sometimes returns NaN on lap 1)
        compound = str(row['Compound']) if isinstance(row['Compound'], str) else "MEDIUM"
        tire_age = int(row['TyreLife']) if not math.isnan(row['TyreLife']) else 1
        
        race_state["drivers"][tla] = {
            "position": position,
            "compound": compound,
            "tire_age": tire_age,
            "gap_to_leader": max(0.0, gap_to_leader),
            "gap_ahead": max(0.0, gap_ahead),
            "gap_behind": 0.0, 
            "drs_train_length": 0 
        }
        
        prev_driver_time = row['Time']
        position += 1

    # Second pass: Calculate who is behind who, and DRS trains
    sorted_tlas = list(race_state["drivers"].keys())
    for i, tla in enumerate(sorted_tlas):
        d_data = race_state["drivers"][tla]
        
        # Calculate gap to the car behind
        if i < len(sorted_tlas) - 1:
            car_behind = sorted_tlas[i+1]
            gap_behind = race_state["drivers"][car_behind]["gap_to_leader"] - d_data["gap_to_leader"]
            d_data["gap_behind"] = max(0.0, gap_behind)
            
        # Flag DRS trains (Under 1 second gap)
        if 0.0 < d_data["gap_ahead"] <= 1.0:
            d_data["drs_train_length"] = 2
    
    # Send the perfect packet to Redis
    r.set('live_f1_state', json.dumps(race_state))
    r.publish('f1_raw_telemetry', json.dumps(race_state))
    
    print(f"🏎️ Streaming Lap {current_lap}/{total_laps} to Dashboard...")
    
    # Wait 2 seconds before sending the next lap so the UI feels "Live"
    time.sleep(2.0) 

print("🏁 REPLAY FINISHED.")
r.delete('live_f1_state') # Clean up when done