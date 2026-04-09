import redis
import json
import concurrent.futures
import gc
import time
import csv
import os
from mcts_strategy import RaceState, run_monte_carlo_engine

DRIVER_SKILLS = {'VER': 0.90, 'HAM': 0.92, 'LEC': 0.98, 'ANT': 0.95, 'NOR': 0.94} 
strategy_cache = {}

def get_sim_budget(position):
    """Safely handles N/A positions for retired drivers to prevent crashes"""
    try:
        pos = int(position)
        if pos <= 5: return 800
        if pos <= 10: return 500
        if pos <= 15: return 200
        return 100
    except:
        return 100 # Fallback for DNF/retired drivers

def should_recompute(driver_code, current_data, current_sc_status):
    if driver_code not in strategy_cache: return True
    
    cached = strategy_cache[driver_code]
    if current_sc_status != cached['sc_active']: return True
    if current_data['compound'] != cached['compound']: return True
    if current_data['position'] != cached['position']: return True
    
    # Recompute if tires aged by 3 laps to keep projections fresh
    if current_data['tire_age'] - cached.get('tire_age', 0) >= 3: return True
    
    gap_a_diff = abs(current_data['gap_ahead'] - cached.get('gap_ahead', 99))
    gap_b_diff = abs(current_data['gap_behind'] - cached.get('gap_behind', 99))
    if gap_a_diff > 0.15 or gap_b_diff > 0.15: return True
    
    return False

def evaluate_driver_strategy(driver_name, d_data, lap, total_laps, is_sc, current_compounds_used):
    compound = d_data['compound']
    if compound in ['UNKNOWN', 'nan', '', 'None']: compound = 'MEDIUM'
    tire_age = max(1, d_data['tire_age'])
    laps_remaining = max(1, total_laps - lap)
    
    # The ONLY bypass: If the race is ending, pitting is useless
    if laps_remaining <= 2:
        return driver_name, "STAY OUT (FINAL LAPS)", compound, 0.0, 0.0

    simulated_track_temp = 45.0 # Miami Dry Heat
    temp_penalty = max(0, (simulated_track_temp - 38.0) * 0.015) 
    sim_budget = get_sim_budget(d_data['position'])

    state = RaceState(
        current_lap=lap, total_laps=total_laps, tire_age=tire_age, compound=compound,
        overtake_difficulty=0.5 + temp_penalty, driver_skill=DRIVER_SKILLS.get(driver_name, 1.0),
        pit_traffic_threats=d_data.get('pit_traffic_threats', 0), compounds_used=set(current_compounds_used),
        track_moisture=0.0, gap_ahead=d_data.get('gap_ahead', 5.0), gap_behind=d_data.get('gap_behind', 5.0),
        enemy_age_ahead=d_data.get('enemy_age_ahead', 10), enemy_age_behind=d_data.get('enemy_age_behind', 10),
        drs_train_length=d_data.get('drs_train_length', 0)
    )
    
    try:
        results = run_monte_carlo_engine(state, is_sc_currently_active=is_sc, num_simulations=sim_budget)
    except TypeError:
        results = run_monte_carlo_engine(state, is_sc_currently_active=is_sc)
        
    best_row = results.iloc[0]
    best_call = best_row['Recommendation']
    opt_time = float(best_row['Projected Time (s)'])
    sub_opt_time = float(results.iloc[1]['Projected Time (s)']) if len(results) > 1 else opt_time + 5.0

    return driver_name, best_call, compound, opt_time, sub_opt_time

def main():
    try:
        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        r.ping()
    except redis.ConnectionError:
        print("❌ ERROR: Could not connect to Redis.")
        return

    pubsub = r.pubsub()
    # 🔥 FIX 1: AI now listens to the RAW pipe
    pubsub.subscribe('f1_raw_telemetry')

    print("=" * 95)
    print("🏁 PITWALL: DRY PERFECT MODEL ONLINE (THREAD POOL FIXED) 🏁")
    print("=" * 95)

    compounds_used_in_race = set()
    log_file = "engine_evaluation_log.csv"
    if os.path.exists(log_file): os.remove(log_file)
        
    with open(log_file, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Lap", "Driver", "Position", "MCTS_Call", "Confidence_Delta_Sec", "Was_Computed", "Total_Lap_Exec_Time"])

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)

    try:
        for message in pubsub.listen():
            if message['type'] == 'message':
                lap_start_time = time.time()
                data = json.loads(message['data'])
                track_name = data['track_name']
                total_laps = data['total_laps']
                lap = data['lap_number']
                is_sc = data['is_sc_active']
                
                print(f"\n🏎️ --- PROCESSING GRID: LAP {lap}/{total_laps} | SC: {is_sc} ---")
                
                to_compute = {}
                for driver_name, d_data in data['drivers'].items():
                    if should_recompute(driver_name, d_data, is_sc):
                        to_compute[driver_name] = d_data
                    else:
                        cached = strategy_cache[driver_name]
                        data['drivers'][driver_name]['recommendation'] = cached['recommendation']
                        data['drivers'][driver_name]['optimal_time'] = cached['optimal_time']
                        data['drivers'][driver_name]['sub_optimal_time'] = cached['sub_optimal_time']

                total_sims = sum(get_sim_budget(to_compute[d].get('position', 99)) for d in to_compute)
                print(f"🧠 Computing: {len(to_compute)} | Cached: {len(data['drivers']) - len(to_compute)} | Total Sims: {total_sims}")
                
                future_to_driver = {
                    executor.submit(evaluate_driver_strategy, driver_name, d_data, lap, total_laps, is_sc, compounds_used_in_race): driver_name 
                    for driver_name, d_data in to_compute.items()
                }
                
                for future in concurrent.futures.as_completed(future_to_driver):
                    try:
                        driver_name, best_call, compound, opt_time, sub_opt_time = future.result()
                        data['drivers'][driver_name]['recommendation'] = best_call
                        data['drivers'][driver_name]['optimal_time'] = opt_time
                        data['drivers'][driver_name]['sub_optimal_time'] = sub_opt_time
                        compounds_used_in_race.add(compound)
                        
                        # Terminal Flex Print for LinkedIn Screenshots
                        position = data['drivers'][driver_name].get('position', 'N/A')
                        call_color = "🔴" if "PIT" in best_call else "🟢"
                        print(f"{call_color} Lap {lap} | P{position} {driver_name} -> {best_call} (Confidence: {round(abs(sub_opt_time-opt_time), 2)}s)")
                        
                        strategy_cache[driver_name] = {
                            'sc_active': is_sc,
                            'position': to_compute[driver_name]['position'],
                            'compound': to_compute[driver_name]['compound'],
                            'tire_age': to_compute[driver_name]['tire_age'],
                            'gap_ahead': to_compute[driver_name].get('gap_ahead', 5.0),
                            'gap_behind': to_compute[driver_name].get('gap_behind', 5.0),
                            'recommendation': best_call,
                            'optimal_time': opt_time,
                            'sub_optimal_time': sub_opt_time
                        }
                    except Exception as e:
                        failed_driver = future_to_driver[future]
                        print(f"⚠️ MCTS Engine hiccup for {failed_driver}: {e}")
                        data['drivers'][failed_driver]['recommendation'] = "COMPUTE_ERROR"
                        data['drivers'][failed_driver]['optimal_time'] = 0.0
                        data['drivers'][failed_driver]['sub_optimal_time'] = 0.0
                
                # 🔥 FIX 2: AI blasts the enriched smart data to the React Dashboard
                r.publish('f1_telemetry_stream', json.dumps(data))
                
                execution_time = time.time() - lap_start_time
                print(f"✅ Grid Lap {lap} Complete in {execution_time:.2f} seconds")
                
                if data['drivers']:
                    with open(log_file, mode='a', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        for driver_name, d_data in data['drivers'].items():
                            opt = d_data.get('optimal_time', 0.0)
                            sub = d_data.get('sub_optimal_time', 0.0)
                            writer.writerow([
                                lap, driver_name, d_data['position'], d_data.get('recommendation', 'UNKNOWN'), 
                                round(abs(sub - opt), 2), "Yes" if driver_name in to_compute else "No", round(execution_time, 2)
                            ])
                gc.collect() 

    except KeyboardInterrupt:
        print("\n🛑 KILL SWITCH ACTIVATED. SHUTTING DOWN INSTANTLY...")
        os._exit(0)

if __name__ == '__main__':
    main()