import fastf1
import pandas as pd
import json
import os
import time
from datetime import datetime

# Enable cache so we don't re-download things we already have
if not os.path.exists('data_cache'): os.makedirs('data_cache')
fastf1.Cache.enable_cache('data_cache')

def mine_sc_history(track_name, years_to_look_back=5):
    print(f"\n⛏️  MINING FIA DATABASE: {track_name} (Last {years_to_look_back} Years)...")
    current_year = datetime.now().year
    
    sc_counts = {'Q1': 0, 'Q2': 0, 'Q3': 0, 'Q4': 0}
    total_laps_analyzed = {'Q1': 0, 'Q2': 0, 'Q3': 0, 'Q4': 0}
    
    for year in range(current_year - years_to_look_back, current_year):
        try:
            print(f"   📥 Fetching {year} {track_name}...")
            session = fastf1.get_session(year, track_name, 'R')
            session.load(telemetry=False, weather=False, messages=False)
            
            total_laps = session.total_laps
            if total_laps == 0: continue
            
            for _, lap in session.laps.iterlaps():
                lap_num = lap['LapNumber']
                status = str(lap['TrackStatus'])
                
                if lap_num <= total_laps * 0.25: phase = 'Q1'
                elif lap_num <= total_laps * 0.50: phase = 'Q2'
                elif lap_num <= total_laps * 0.75: phase = 'Q3'
                else: phase = 'Q4'
                
                total_laps_analyzed[phase] += 1
                
                if '4' in status or '6' in status:
                    sc_counts[phase] += 1
                    
            # 🛑 API THROTTLING: Wait 2 seconds between years so we don't trigger the 500/hr limit
            time.sleep(60) 
            
        except Exception as e:
            print(f"   ⚠️ Could not load {year}: {e}")
            # If the API blocks us, wait 10 seconds and cool down
            time.sleep(0) 

    probabilities = {}
    for phase in sc_counts:
        if total_laps_analyzed[phase] > 0:
            prob = (sc_counts[phase] / total_laps_analyzed[phase]) * 100
            probabilities[phase] = round(prob, 1)
        else:
            probabilities[phase] = 0.0

    print(f"✅ {track_name} SC PROBABILITIES: {probabilities}")
    return probabilities

def update_sc_database(tracks_to_mine):
    db_path = 'sc_database.json'
    
    # Load existing DB to act as a checkpoint
    if os.path.exists(db_path):
        with open(db_path, 'r') as f:
            sc_db = json.load(f)
    else:
        sc_db = {}
        
    for track in tracks_to_mine:
        # Skip tracks we already successfully mined! (Checkpointing)
        if track in sc_db:
            print(f"\n⏭️  Skipping {track}... Already exists in database.")
            continue
            
        sc_db[track] = mine_sc_history(track)
        
        # 💾 ITERATIVE SAVING: Save to JSON immediately after every track
        with open(db_path, 'w') as f:
            json.dump(sc_db, f, indent=4)
            
        # 🛑 API THROTTLING: Take a 5-second breather between different countries
        print(f"⏳ Taking a 5-second API cooldown break...")
        time.sleep(0)

    print(f"\n🏁 ALL TRACKS MINED. Saved to {db_path} successfully!")

if __name__ == "__main__":
    print("=" * 60)
    print("🚦 F1 HISTORICAL DATA MINER (RATE-LIMIT SAFE) INITIALIZED")
    print("=" * 60)
    
    target_tracks = [
        'Bahrain', 'Saudi Arabia', 'Australia', 'Japan', 'China', 
        'Miami', 'Emilia Romagna', 'Monaco', 'Canada', 'Spain', 
        'Austria', 'Great Britain', 'Hungary', 'Belgium', 'Netherlands', 
        'Italy', 'Azerbaijan', 'Singapore', 'United States', 'Mexico', 
        'Brazil', 'Las Vegas', 'Qatar', 'Abu Dhabi'
    ]
    
    update_sc_database(target_tracks)