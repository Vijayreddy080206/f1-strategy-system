from fastf1.livetiming.client import SignalRClient
import redis
import time
import json
import threading
import os

# ==============================================================================
# CONFIGURATION
# ==============================================================================
LIVE_DATA_FILE = 'live_telemetry_dump.txt'

try:
    r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    r.ping()
    print("✅ Connected to Redis Master!")
except redis.ConnectionError:
    print("❌ ERROR: Could not connect to Redis. Start your Redis server!")
    exit()

# ==============================================================================
# GLOBAL STATE MEMORY (The AI relies on this being updated via Deltas)
# ==============================================================================
driver_mapping = {}  # Maps F1 Driver Numbers to 3-Letter Acronyms (e.g., '1' -> 'VER')

race_state = {
    "track_name": "Live Grand Prix",
    "total_laps": 60, # Will update dynamically
    "lap_number": 1,
    "track_moisture": 0.0,
    "is_sc_active": False,
    "sc_probabilities": {"Q1": 15, "Q2": 20, "Q3": 45, "Q4": 10}, # Placeholder stats
    "drivers": {}
}

def create_default_driver():
    return {
        "compound": "MEDIUM", "tire_age": 1, "position": 99,
        "gap_to_leader": 0.0, "gap_ahead": 0.0, "gap_behind": 0.0,
        "pit_traffic_threats": 0, "threat_names": "Clear Air",
        "enemy_age_ahead": 0, "enemy_age_behind": 0,
        "drs_train_length": 0, "combat_radar": "Clear Air"
    }

def safe_float(val):
    """Safely converts F1 string gaps ('+5.234') to floats."""
    if not val: return 0.0
    try:
        val = str(val).replace('+', '').replace('LAP', '').strip()
        if 'S' in val.upper() or val == '': return 0.0 # Catch weird edge cases
        return float(val)
    except:
        return 0.0

# ==============================================================================
# THE PARSER: Translates F1 Raw JSON Deltas into MCTS Memory
# ==============================================================================
def process_live_delta(packet):
    global race_state, driver_mapping
    
    # 1. DRIVER LIST (Grabs the names at the start of the session)
    if 'DriverList' in packet:
        for num, info in packet['DriverList'].items():
            tla = info.get('Tla', f"UNK_{num}")
            driver_mapping[num] = tla
            if tla not in race_state["drivers"]:
                race_state["drivers"][tla] = create_default_driver()

    # 2. TRACK STATUS (Safety Car / VSC Detection)
    if 'TrackStatus' in packet:
        status = packet['TrackStatus'].get('Status', '1')
        # F1 Codes: 4 = Safety Car, 6 = VSC
        race_state['is_sc_active'] = (status == '4' or status == '6')

    # 3. WEATHER DATA
    if 'WeatherData' in packet:
        # F1 API uses 0 for dry, 1 for wet, but also broadcasts track temp/humidity
        humidity = safe_float(packet['WeatherData'].get('Humidity', 0))
        rainfall = packet['WeatherData'].get('Rainfall', '0')
        race_state['track_moisture'] = humidity if rainfall == '1' else 0.0

    # 4. TIMING DATA (Positions, Lap Number, Gaps)
    if 'TimingData' in packet and 'Lines' in packet['TimingData']:
        for num, data in packet['TimingData']['Lines'].items():
            tla = driver_mapping.get(num)
            if not tla or tla not in race_state['drivers']: continue
            
            if 'Position' in data:
                race_state['drivers'][tla]['position'] = int(data['Position'])
            if 'GapToLeader' in data:
                race_state['drivers'][tla]['gap_to_leader'] = safe_float(data['GapToLeader'])
            if 'NumberOfLaps' in data:
                # Update global lap based on the leader's lap
                if race_state['drivers'][tla]['position'] == 1:
                    race_state['lap_number'] = int(data['NumberOfLaps'])

    # 5. TIMING APP DATA (The Tire Sensors!)
    if 'TimingAppData' in packet and 'Lines' in packet['TimingAppData']:
        for num, data in packet['TimingAppData']['Lines'].items():
            tla = driver_mapping.get(num)
            if not tla or tla not in race_state['drivers']: continue
            
            if 'Stints' in data:
                stints = data['Stints']
                if not stints: continue
                
                # The last item in the list is their current stint
                current_stint = stints[-1]
                if isinstance(current_stint, dict):
                    if 'Compound' in current_stint:
                        race_state['drivers'][tla]['compound'] = str(current_stint['Compound'])
                    if 'TotalLaps' in current_stint:
                        race_state['drivers'][tla]['tire_age'] = int(current_stint['TotalLaps'])

# ==============================================================================
# COMBAT & TRAFFIC MATH (Runs 1x per second before broadcasting)
# ==============================================================================
def enrich_global_state():
    """Calculates who is fighting who based on the parsed gaps to the leader."""
    # Sort drivers by position
    sorted_drivers = sorted(
        [d for d in race_state['drivers'].keys()], 
        key=lambda x: race_state['drivers'][x]['position']
    )
    
    for i, driver in enumerate(sorted_drivers):
        d_data = race_state['drivers'][driver]
        
        # Calculate Gap Ahead
        if i == 0:
            d_data['gap_ahead'] = 0.0
        else:
            car_ahead = sorted_drivers[i-1]
            gap = safe_float(d_data['gap_to_leader']) - safe_float(race_state['drivers'][car_ahead]['gap_to_leader'])
            d_data['gap_ahead'] = round(max(0.0, gap), 2)
            
        # Calculate Gap Behind
        if i == len(sorted_drivers) - 1:
            d_data['gap_behind'] = 99.0
        else:
            car_behind = sorted_drivers[i+1]
            gap = safe_float(race_state['drivers'][car_behind]['gap_to_leader']) - safe_float(d_data['gap_to_leader'])
            d_data['gap_behind'] = round(max(0.0, gap), 2)
            
        # Combat Radar Logic
        combat = []
        if 0 < d_data['gap_ahead'] <= 1.0:
            combat.append(f"🎯 DRS on {sorted_drivers[i-1]}")
            d_data['drs_train_length'] = 2 # Simplification for live stream
        else:
            d_data['drs_train_length'] = 0
            
        if 0 < d_data['gap_behind'] <= 1.0:
            combat.append(f"⚠️ {sorted_drivers[i+1]} in DRS")
            
        d_data['combat_radar'] = " | ".join(combat) if combat else "Clear Air"

# ==============================================================================
# THE MAIN LOOP
# ==============================================================================
def start_f1_client():
    print("📡 Connecting to official FIA SignalR Live WebSocket...")
    client = SignalRClient(filename=LIVE_DATA_FILE)
    client.start() 

def tail_and_broadcast():
    print("👀 Waiting for race to begin. Tailing live data...")
    
    while not os.path.exists(LIVE_DATA_FILE):
        time.sleep(1)

    last_broadcast_time = time.time()
    
    with open(LIVE_DATA_FILE, 'r') as file:
        file.seek(0, 2) # Jump to the end of the file to ignore old data
        
        while True:
            line = file.readline()
            
            if line:
                try:
                    packet = json.loads(line)
                    process_live_delta(packet)
                except json.JSONDecodeError:
                    pass # Ignore connection pings
            else:
                # No new data arrived yet, wait 50ms
                time.sleep(0.05)
                
            # Broadcast the fully enriched state to AI & React every 1.0 seconds
            current_time = time.time()
            if current_time - last_broadcast_time >= 1.0:
                if len(race_state['drivers']) > 0:
                    enrich_global_state()
                    r.set('live_f1_state', json.dumps(race_state))
                    r.publish('f1_raw_telemetry', json.dumps(race_state))
                last_broadcast_time = current_time

if __name__ == "__main__":
    if os.path.exists(LIVE_DATA_FILE):
        os.remove(LIVE_DATA_FILE)

    # Boot the connection in the background
    threading.Thread(target=start_f1_client, daemon=True).start()

    try:
        # Start the parsing and broadcasting engine
        tail_and_broadcast()
    except KeyboardInterrupt:
        print("\n🛑 SHUTTING DOWN LIVE FEED...")
        os._exit(0)