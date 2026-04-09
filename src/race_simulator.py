"""
F1 Race Simulator — Industry-level environment for RL training.

Observation space: 20 values matching real race conditions exactly.
The agent trains on the same signals it will see during live races.

State vector:
 0  lap_progress              — % of race complete
 1  tire_age_norm             — laps on current tire / 50
 2  compound_norm             — Soft=0, Medium=0.33, Hard=0.67
 3  gap_ahead_norm            — gap to car ahead / 60
 4  gap_behind_norm           — gap to car behind / 60
 5  fuel_load_norm            — fuel remaining / 100
 6  sc_probability            — 0-1 safety car likelihood
 7  pit_count_norm            — pit stops made / 4
 8  laps_since_pit_norm       — laps since last stop / 50
 9  rival_ahead_age_norm      — rival ahead tire age / 50
10  rival_behind_age_norm     — rival behind tire age / 50
11  rival_ahead_compound      — rival ahead compound / 3
12  rival_behind_compound     — rival behind compound / 3
13  laps_stuck_norm           — laps stuck behind rival / 10
14  overtake_difficulty       — 0=easy, 0.5=hard, 1=impossible
15  rain_probability          — 0-1
16  vsc_active                — 0/1
17  graining_flag             — 0/1
18  rival_ahead_near_cliff    — 0/1 rival approaching cliff
19  position_norm             — current position / 20
"""

import numpy as np
import gymnasium as gym
from gymnasium import spaces
import joblib
import pandas as pd
import os
import json

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH  = os.path.join(BASE_DIR, 'models', 'degradation', 'xgb_model.pkl')
CONFIG_PATH = os.path.join(BASE_DIR, 'models', 'degradation', 'model_config.json')

# Compound cliff laps — when each tire type genuinely dies
COMPOUND_CLIFF = {0: 18, 1: 28, 2: 38}   # Soft, Medium, Hard
COMPOUND_NAMES = {0: 'Soft', 1: 'Medium', 2: 'Hard'}

# Overtake difficulty by circuit type
# 0.0 = easy (Monza), 1.0 = impossible (Monaco)
CIRCUIT_OVERTAKE_DIFFICULTY = {
    0: 0.3,   # Australian — medium
    1: 0.2,   # Bahrain — easy/medium
    2: 0.5,   # Chinese — medium
    3: 1.0,   # Monaco — impossible
    4: 0.6,   # Singapore — very hard
    5: 0.15,  # Italian (Monza) — easy
    6: 0.15,  # Belgian — easy
    7: 0.25,  # British — medium
    8: 0.35,  # Spanish — medium
    9: 0.65,  # Hungarian — hard
}

# Driver tire management ratings (how well they extend tire life)
DRIVER_MGT_RATINGS = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]


class F1RaceSimulator(gym.Env):
    """
    Industry-level F1 race strategy environment.
    20-dimensional observation matching real race conditions.
    Simulates: rivals, traffic, graining, VSC, weather, overtaking difficulty.
    """

    def __init__(self, total_laps=57, circuit_code=0, track_temp=35.0):
        super().__init__()

        self.total_laps   = total_laps
        self.circuit_code = circuit_code
        self.track_temp   = track_temp

        # Load degradation model
        try:
            self.deg_model = joblib.load(MODEL_PATH)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Degradation model not found at: {MODEL_PATH}\n"
                "Run: python src/degradation_model.py first"
            )

        # Load feature config
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            self.features = cfg.get(
                'features',
                ['TyreLife', 'CompoundEncoded', 'CircuitEncoded', 'TrackTemp']
            )
        except Exception:
            self.features = [
                'TyreLife', 'CompoundEncoded', 'CircuitEncoded', 'TrackTemp'
            ]

        # 20-value observation space — all normalized to [0, 1]
        self.observation_space = spaces.Box(
            low  = np.zeros(20, dtype=np.float32),
            high = np.ones(20,  dtype=np.float32)
        )

        # 4 actions: stay out / pit Medium / pit Hard / pit Soft
        self.action_space = spaces.Discrete(4)

        # Overtake difficulty for this circuit
        self.overtake_diff = CIRCUIT_OVERTAKE_DIFFICULTY.get(
            circuit_code % 10, 0.4
        )

        self._init_state()

    # ── State initialization ───────────────────────────────────────────────
    def _init_state(self):
        self.current_lap         = 1
        self.tire_age            = 0
        self.compound            = 1          # start on Medium
        self.position            = 10
        self.gap_ahead           = 5.0
        self.gap_behind          = 5.0
        self.sc_probability      = 0.03
        self.total_time          = 0.0
        self.pit_count           = 0
        self.laps_since_last_pit = 0
        self.sc_active           = False
        self.sc_laps_left        = 0
        self.vsc_active          = False
        self.vsc_laps_left       = 0
        self.rain_probability    = 0.05
        self.graining            = False
        self.graining_laps       = 0
        self.laps_stuck          = 0

        # Driver management rating (random per episode)
        self.driver_mgmt = float(np.random.choice(DRIVER_MGT_RATINGS))

        # Adjusted cliff based on driver management
        self.compound_cliffs = {
            k: int(v * self.driver_mgmt)
            for k, v in COMPOUND_CLIFF.items()
        }

        # Simulate 5 rival cars — each with own tire state
        n_rivals = 5
        self.rival_compounds    = np.random.randint(0, 3, size=n_rivals)
        self.rival_tire_ages    = np.random.uniform(0, 12, size=n_rivals)
        self.rival_pit_counts   = np.zeros(n_rivals, dtype=int)
        self.rival_mgmt_ratings = np.random.choice(
            DRIVER_MGT_RATINGS, size=n_rivals
        )

        # Rival positions relative to us
        # rival 0 = directly ahead, rival 1 = second ahead
        # rival 2 = directly behind, rival 3 = second behind
        # rival 4 = further back

    # ── Degradation prediction ─────────────────────────────────────────────
    def _get_deg(self, tire_age, compound_code, lap=None):
        if lap is None:
            lap = self.current_lap
        sample = {f: 0.0 for f in self.features}
        sample['TyreLife']        = float(max(0, tire_age))
        sample['CompoundEncoded'] = float(compound_code)
        sample['CircuitEncoded']  = float(self.circuit_code)
        sample['TrackTemp']       = float(self.track_temp)
        if 'RaceProgressFraction' in self.features:
            sample['RaceProgressFraction'] = float(lap) / float(self.total_laps)
        if 'LapTimeDelta_prev' in self.features:
            sample['LapTimeDelta_prev'] = 0.0
        if 'FuelLoad' in self.features:
            sample['FuelLoad'] = max(0.0, 100 - lap * 1.8)
        s = pd.DataFrame([sample])
        return max(0.0, float(self.deg_model.predict(s)[0]))

    # ── Graining simulation ────────────────────────────────────────────────
    def _update_graining(self, compound, tire_age):
        """
        Graining happens on Soft tires in early stint (laps 3-8).
        Performance temporarily worse then recovers as rubber clears.
        """
        if compound == 0 and 3 <= tire_age <= 9:
            if not self.graining and np.random.random() < 0.3:
                self.graining      = True
                self.graining_laps = 0
        elif self.graining:
            self.graining_laps += 1
            if self.graining_laps >= 5:  # graining clears after ~5 laps
                self.graining      = False
                self.graining_laps = 0

    # ── Rival car update ───────────────────────────────────────────────────
    def _update_rivals(self):
        """
        Advance rival tire ages and make intelligent pit decisions.
        Rivals pit when:
        - Past their compound cliff (adjusted for mgmt rating)
        - Under SC/VSC (free stop)
        - Responding to our pit (covering undercut)
        """
        for i in range(len(self.rival_compounds)):
            self.rival_tire_ages[i] += 1
            adj_cliff = int(
                COMPOUND_CLIFF[self.rival_compounds[i]]
                * self.rival_mgmt_ratings[i]
            )

            # Rival pit decision
            should_pit = False

            # Past cliff — must pit
            if self.rival_tire_ages[i] > adj_cliff + np.random.randint(0, 5):
                should_pit = True

            # SC/VSC — free stop
            if (self.sc_active or self.vsc_active) and self.rival_tire_ages[i] > 8:
                if np.random.random() < 0.6:  # 60% take the free stop
                    should_pit = True

            # Random strategy variation (teams stagger stops)
            if (self.rival_tire_ages[i] > adj_cliff * 0.7
                    and np.random.random() < 0.02):
                should_pit = True

            if should_pit:
                # Reset to fresh tires
                self.rival_tire_ages[i]   = 0
                # Choose new compound based on laps remaining
                laps_left = self.total_laps - self.current_lap
                if laps_left > 25:
                    self.rival_compounds[i] = 2  # Hard for long runs
                elif laps_left > 12:
                    self.rival_compounds[i] = 1  # Medium
                else:
                    self.rival_compounds[i] = 0  # Soft for final push
                self.rival_pit_counts[i] += 1

    # ── Gap dynamics ───────────────────────────────────────────────────────
    def _update_gaps(self, my_lap_time):
        """
        Update gaps based on relative lap times.
        Rival directly ahead = rival[0], directly behind = rival[2].
        Accounts for overtaking difficulty — hard to close gap at Monaco.
        """
        # Rival ahead
        rival_ahead_deg = self._get_deg(
            self.rival_tire_ages[0],
            self.rival_compounds[0]
        )
        rival_ahead_time = 90.0 + rival_ahead_deg
        if self.sc_active or self.vsc_active:
            rival_ahead_time += 30.0

        delta_ahead = my_lap_time - rival_ahead_time
        # Overtaking difficulty reduces effective gap closure
        gap_change_ahead = delta_ahead * (1.0 - self.overtake_diff * 0.5)
        self.gap_ahead += gap_change_ahead * float(np.random.uniform(0.3, 0.6))
        self.gap_ahead = float(np.clip(self.gap_ahead, -60, 60))

        # Rival behind
        rival_behind_deg  = self._get_deg(
            self.rival_tire_ages[2],
            self.rival_compounds[2]
        )
        rival_behind_time = 90.0 + rival_behind_deg
        if self.sc_active or self.vsc_active:
            rival_behind_time += 30.0

        delta_behind = rival_behind_time - my_lap_time
        self.gap_behind += delta_behind * float(np.random.uniform(0.3, 0.6))
        self.gap_behind = float(np.clip(self.gap_behind, -60, 60))

        # Track position changes
        if self.gap_ahead > 0 and self.position > 1:
            # Overtake only possible if gap opens AND circuit allows it
            if (np.random.random() > self.overtake_diff
                    or self.gap_ahead > 15):
                self.position  -= 1
                self.gap_ahead  = -abs(self.gap_ahead * 0.4)

        if self.gap_behind > 0 and self.position < 20:
            if (np.random.random() > self.overtake_diff
                    or self.gap_behind > 15):
                self.position   += 1
                self.gap_behind  = -abs(self.gap_behind * 0.4)

        # Count laps stuck behind rival ahead
        if -3.0 < self.gap_ahead < 0.5:
            self.laps_stuck += 1
        else:
            self.laps_stuck = 0

    # ── SC/VSC probability ─────────────────────────────────────────────────
    def _update_track_status(self):
        base_sc  = 0.03 + (self.current_lap / self.total_laps) * 0.04

        if self.sc_active:
            self.sc_laps_left -= 1
            if self.sc_laps_left <= 0:
                self.sc_active = False
        elif self.vsc_active:
            self.vsc_laps_left -= 1
            if self.vsc_laps_left <= 0:
                self.vsc_active = False
        else:
            r = np.random.random()
            if r < base_sc * 0.6:      # Full SC
                self.sc_active    = True
                self.sc_laps_left = int(np.random.randint(3, 7))
            elif r < base_sc:           # VSC (more common, cheaper)
                self.vsc_active    = True
                self.vsc_laps_left = int(np.random.randint(2, 5))

        self.sc_probability = min(base_sc * 2, 0.15)

    def _update_weather(self):
        """Rain probability drifts slowly throughout race."""
        drift = np.random.normal(0, 0.01)
        self.rain_probability = float(
            np.clip(self.rain_probability + drift, 0.0, 0.95)
        )

    # ── Observation builder ────────────────────────────────────────────────
    def _get_obs(self):
        # Check if rival ahead is near cliff
        rival_ahead_cliff = COMPOUND_CLIFF[self.rival_compounds[0]]
        rival_adj_cliff   = int(
            rival_ahead_cliff * self.rival_mgmt_ratings[0]
        )
        rival_near_cliff  = float(
            self.rival_tire_ages[0] > rival_adj_cliff * 0.85
        )

        return np.array([
            # Core race state
            self.current_lap         / self.total_laps,        # 0
            self.tire_age            / 50.0,                   # 1
            self.compound            / 3.0,                    # 2
            np.clip(self.gap_ahead,  -60, 60) / 60.0,         # 3
            np.clip(self.gap_behind, -60, 60) / 60.0,         # 4
            max(0, 100 - self.current_lap * 1.8) / 100.0,     # 5  fuel
            self.sc_probability,                               # 6

            # Stop history
            min(self.pit_count, 4)   / 4.0,                   # 7
            self.laps_since_last_pit / 50.0,                   # 8

            # Rival state — directly ahead
            float(np.clip(self.rival_tire_ages[0], 0, 50)) / 50.0,  # 9
            # Rival state — directly behind
            float(np.clip(self.rival_tire_ages[2], 0, 50)) / 50.0,  # 10
            self.rival_compounds[0]  / 3.0,                   # 11
            self.rival_compounds[2]  / 3.0,                   # 12

            # Traffic and overtaking
            min(self.laps_stuck, 10) / 10.0,                  # 13
            self.overtake_diff,                                # 14

            # Weather and track status
            self.rain_probability,                             # 15
            float(self.vsc_active),                            # 16

            # Tire condition
            float(self.graining),                              # 17

            # Rival strategic signals
            rival_near_cliff,                                  # 18

            # Position
            self.position            / 20.0,                  # 19
        ], dtype=np.float32)

    # ── Gym interface ──────────────────────────────────────────────────────
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self._init_state()

        # Randomize starting conditions
        self.position              = int(np.random.randint(3, 16))
        self.gap_ahead             = float(np.random.uniform(0.5, 25))
        self.gap_behind            = float(np.random.uniform(0.5, 20))
        self.rain_probability      = float(np.random.uniform(0.02, 0.20))

        # Randomize rival tire ages realistically
        # (they started race at lap 0 too, some may have already pitted)
        self.rival_tire_ages = np.random.uniform(0, 15, size=5)

        return self._get_obs(), {}

    def step(self, action):
        action = int(action)

        # ── Track and weather updates ─────────────────────────────────────
        self._update_track_status()
        self._update_weather()
        self._update_graining(self.compound, self.tire_age)
        self._update_rivals()

        # ── Pit stop ─────────────────────────────────────────────────────
        pit_penalty = 0.0
        if action > 0:
            compound_map          = {1: 1, 2: 2, 3: 0}
            self.compound         = compound_map[action]
            self.tire_age         = 0
            self.pit_count       += 1
            self.laps_since_last_pit = 0
            self.graining         = False   # new tire, no graining
            self.laps_stuck       = 0

            # Pit cost: SC=5.5s, VSC=10s, normal=22s
            if self.sc_active:
                pit_penalty = 5.5
            elif self.vsc_active:
                pit_penalty = 10.0
            else:
                pit_penalty = 22.0

            # Rival covering strategy — rival behind may also pit
            # if we pit (defensive cover)
            if (self.gap_behind < 3.0 and self.rival_tire_ages[2] > 8):
                if np.random.random() < 0.45:  # 45% chance they cover
                    self.rival_tire_ages[2] = 0
                    self.rival_compounds[2] = compound_map[action]

        # ── Lap time calculation ──────────────────────────────────────────
        deg        = self._get_deg(self.tire_age, self.compound)
        sc_delta   = 30.0 if (self.sc_active or self.vsc_active) else 0.0

        # Graining adds time (0.3-0.8s) but reduces as it clears
        graining_delta = 0.0
        if self.graining:
            graining_delta = max(
                0.0, 0.6 - self.graining_laps * 0.12
            )

        # Rain adds time if probability very high
        rain_delta = 3.0 if self.rain_probability > 0.85 else 0.0

        lap_time = (90.0 + deg + pit_penalty + sc_delta
                    + graining_delta + rain_delta)
        self.total_time += lap_time

        # ── Update gaps ───────────────────────────────────────────────────
        self._update_gaps(lap_time)

        # ── Reward calculation ────────────────────────────────────────────
        cliff_adj = self.compound_cliffs.get(self.compound, 28)

        # Position reward — better position = higher reward
        position_bonus  = (20 - self.position) * 0.5

        # Pit penalty — discourage excessive stops but allow 2
        if self.pit_count <= 2:
            pit_rew_penalty = self.pit_count * 1.0
        else:
            pit_rew_penalty = 2.0 + (self.pit_count - 2) * 5.0

        # Cliff penalty — heavy cost for staying out past cliff
        over_cliff      = max(0, self.tire_age - cliff_adj)
        cliff_penalty   = over_cliff * 5.0

        # Traffic penalty — stuck behind slower car on hard-to-pass circuit
        traffic_penalty = 0.0
        if (self.laps_stuck > 3
                and self.overtake_diff > 0.6
                and action == 0):
            traffic_penalty = self.laps_stuck * 1.5

        # Graining penalty — flag this is costing time
        graining_penalty = graining_delta * 2.0

        # Reward for smart use of SC/VSC window
        sc_pit_bonus = 0.0
        if (action > 0 and (self.sc_active or self.vsc_active)
                and self.tire_age > cliff_adj * 0.4):
            sc_pit_bonus = 15.0  # big bonus for taking free stop correctly

        # Rival undercut protection bonus
        undercut_protect_bonus = 0.0
        if (action > 0
                and self.gap_behind < 2.5
                and self.rival_tire_ages[2] > self.rival_mgmt_ratings[2]
                * COMPOUND_CLIFF[self.rival_compounds[2]] * 0.85):
            undercut_protect_bonus = 8.0  # protected from undercut

        # Rain compound bonus — pitting for wet tires when rain likely
        rain_bonus = 0.0
        if action > 0 and self.rain_probability > 0.7:
            rain_bonus = 10.0

        # Window reward — bonus for pitting at RIGHT time
        # (not too early, not past cliff)
        timing_bonus = 0.0
        if action > 0:
            pct_through_window = self.tire_age / cliff_adj if cliff_adj > 0 else 1
            if 0.7 <= pct_through_window <= 1.0:
                timing_bonus = 5.0   # ideal window
            elif pct_through_window < 0.4:
                timing_bonus = -8.0  # too early

        reward = (
            -lap_time * 0.1
            + position_bonus
            - pit_rew_penalty
            - cliff_penalty
            - traffic_penalty
            - graining_penalty
            + sc_pit_bonus
            + undercut_protect_bonus
            + rain_bonus
            + timing_bonus
        )

        # ── Advance state ─────────────────────────────────────────────────
        self.tire_age            += 1
        self.laps_since_last_pit += 1
        self.current_lap         += 1

        done = self.current_lap > self.total_laps

        info = {
            'lap':            self.current_lap,
            'tire_age':       self.tire_age,
            'compound':       self.compound,
            'position':       self.position,
            'lap_time':       round(lap_time, 3),
            'pit_count':      self.pit_count,
            'sc_active':      self.sc_active,
            'vsc_active':     self.vsc_active,
            'graining':       self.graining,
            'laps_stuck':     self.laps_stuck,
            'rain_prob':      round(self.rain_probability, 3),
            'cliff_lap':      cliff_adj,
            'overtake_diff':  self.overtake_diff,
            'rival_ahead_age': int(self.rival_tire_ages[0]),
            'rival_behind_age': int(self.rival_tire_ages[2]),
        }

        return self._get_obs(), float(reward), done, False, info