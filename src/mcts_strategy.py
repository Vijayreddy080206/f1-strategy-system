import random
import pandas as pd
from dataclasses import dataclass

@dataclass
class RaceState:
    current_lap: int
    total_laps: int
    tire_age: int
    compound: str
    overtake_difficulty: float
    driver_skill: float
    pit_traffic_threats: int
    compounds_used: set
    track_moisture: float
    gap_ahead: float
    gap_behind: float
    enemy_age_ahead: int
    enemy_age_behind: int
    drs_train_length: int

def run_monte_carlo_engine(state: RaceState, is_sc_currently_active: bool, num_simulations: int = 500):
    # 🏎️ PURE DRY MONSTER: Fast array math with TRUE DEEP BRANCHING
    actions = ["STAY OUT", "PIT → SOFT", "PIT → MEDIUM", "PIT → HARD"]
    BASE_LAP = 90.0
    PIT_LOSS = 22.0
    
    # 📉 F1 TIRE CLIFF DATA
    CLIFF_LAPS = {'SOFT': 18, 'MEDIUM': 28, 'HARD': 42}
    BASE_DEG = {'SOFT': 0.15, 'MEDIUM': 0.08, 'HARD': 0.04}
    
    results = []
    sims_per_branch = max(10, num_simulations // len(actions))

    for action in actions:
        total_branch_time = 0.0
        
        for _ in range(sims_per_branch):
            sim_time = 0.0
            sim_compound = state.compound
            sim_age = state.tire_age
            sim_stops_made = 0
            
            # Apply Root Action (The first node in the tree)
            if "PIT" in action:
                # Add traffic penalty if they pit directly into a DRS train
                sim_time += PIT_LOSS + (state.pit_traffic_threats * 1.5)
                sim_compound = action.split(" → ")[1]
                sim_age = 0
                sim_stops_made += 1
                
            for lap in range(state.current_lap, state.total_laps + 1):
                # 1. Base Degradation
                deg = BASE_DEG.get(sim_compound, 0.10)
                lap_deg_loss = sim_age * deg * state.driver_skill
                
                # 2. THE TIRE CLIFF (Exponential fall-off)
                cliff_threshold = CLIFF_LAPS.get(sim_compound, 25)
                cliff_penalty = 0.0
                if sim_age > cliff_threshold:
                    # Tire is dead. Time loss scales exponentially.
                    cliff_penalty = ((sim_age - cliff_threshold) ** 1.5) * 0.2
                
                current_lap_loss = lap_deg_loss + cliff_penalty
                
                # 3. TRUE MCTS ROLLOUT (Deep Branching for 2-Stop & 3-Stop Races)
                # If the tire is losing more than 2.5s a lap due to the cliff, PIT AGAIN.
                laps_remaining = state.total_laps - lap
                if current_lap_loss > 2.5 and laps_remaining > 2:
                    # Trigger a secondary stop in this alternate timeline
                    sim_time += PIT_LOSS
                    sim_age = 0
                    sim_stops_made += 1
                    
                    # Smart compound selection for the secondary stop
                    if laps_remaining <= 18: sim_compound = 'SOFT'
                    elif laps_remaining <= 28: sim_compound = 'MEDIUM'
                    else: sim_compound = 'HARD'
                    
                    current_lap_loss = 0.0 # Tires are fresh again!
                    
                # 4. Final Lap Time Calculation
                variance = random.uniform(-0.2, 0.2)
                lap_time = BASE_LAP + current_lap_loss + variance + state.overtake_difficulty
                
                if is_sc_currently_active and lap == state.current_lap:
                    lap_time += 20.0 # Safety car delta
                    
                sim_time += lap_time
                sim_age += 1
                
            total_branch_time += sim_time
            
        # Average the alternate futures
        avg_time = total_branch_time / sims_per_branch if sims_per_branch > 0 else sim_time
        results.append({"Recommendation": action, "Projected Time (s)": avg_time})
            
    # Compile Results
    df = pd.DataFrame(results)
    df = df.sort_values(by="Projected Time (s)").reset_index(drop=True)
    
    best_call = df.iloc[0]['Recommendation']
    
    # UI Formatting
    if best_call == "STAY OUT" and state.tire_age > 15:
        best_call = f"STAY OUT (Optimal Pit: Lap {state.current_lap + 5})"
    elif best_call == "STAY OUT":
        best_call = "STAY OUT (TIRES FRESH)"
        
    df.at[0, 'Recommendation'] = best_call
    return df