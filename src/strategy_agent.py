import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stable_baselines3 import DQN
from stable_baselines3.common.evaluation import evaluate_policy
from stable_baselines3.common.monitor import Monitor
from race_simulator import F1RaceSimulator

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAVE_PATH = os.path.join(BASE_DIR, 'models', 'strategy', 'dqn_agent')

COMPOUND_NAMES = {0: 'Soft', 1: 'Medium', 2: 'Hard'}
ACTION_NAMES   = {
    0: 'Stay out  ',
    1: 'Pit→Medium',
    2: 'Pit→Hard  ',
    3: 'Pit→Soft  '
}


def train_agent():
    print("=" * 60)
    print("F1 STRATEGY RL AGENT — INDUSTRY-LEVEL TRAINING")
    print("=" * 60)

    # Verify environment
    test_env = F1RaceSimulator()
    obs, _   = test_env.reset()
    print(f"\nObservation space: {len(obs)} inputs")
    print("Inputs the agent sees every lap:")
    input_names = [
        " 0  Lap progress (% of race done)",
        " 1  Tire age (laps on current set)",
        " 2  Compound (Soft/Medium/Hard)",
        " 3  Gap to car ahead",
        " 4  Gap to car behind",
        " 5  Fuel load remaining",
        " 6  Safety car probability",
        " 7  Pit stops made so far",
        " 8  Laps since last pit stop",
        " 9  Rival AHEAD tire age",
        "10  Rival BEHIND tire age",
        "11  Rival AHEAD compound",
        "12  Rival BEHIND compound",
        "13  Laps stuck in traffic",
        "14  Overtaking difficulty (circuit)",
        "15  Rain probability",
        "16  VSC active flag",
        "17  Graining detected flag",
        "18  Rival ahead approaching cliff",
        "19  Current position",
    ]
    for name in input_names:
        print(f"     {name}")

    print(f"\nAction space: {test_env.action_space.n} actions")
    print("     0 = Stay out")
    print("     1 = Pit for Medium")
    print("     2 = Pit for Hard")
    print("     3 = Pit for Soft")
    test_env.close()

    print("\nSetting up training environment...")
    env = Monitor(F1RaceSimulator())

    print("Creating DQN agent...")
    model = DQN(
        "MlpPolicy",
        env,
        learning_rate=0.0003,
        buffer_size=150000,      # larger buffer for complex obs space
        learning_starts=8000,    # more warmup for 20-input space
        batch_size=256,
        gamma=0.99,
        exploration_fraction=0.35,
        exploration_final_eps=0.04,
        verbose=1,
        policy_kwargs=dict(
            net_arch=[256, 256, 128]  # deeper network for complex inputs
        )
    )

    print("\nTraining — 45-60 mins. Do not close terminal.")
    print("Watch ep_rew_mean rise and loss fall.\n")

    model.learn(total_timesteps=400000)

    os.makedirs(os.path.join(BASE_DIR, 'models', 'strategy'), exist_ok=True)
    model.save(SAVE_PATH)
    print(f"\n✅ Agent saved to {SAVE_PATH}")

    # Evaluate
    print("\nEvaluating over 20 races...")
    eval_env = Monitor(F1RaceSimulator())
    mean_reward, std_reward = evaluate_policy(
        model, eval_env, n_eval_episodes=20, warn=False
    )
    print(f"Mean reward: {mean_reward:.2f} +/- {std_reward:.2f}")
    eval_env.close()

    # Sample race with full decision breakdown
    print("\n" + "=" * 60)
    print("SAMPLE RACE — FULL DECISION BREAKDOWN")
    print("=" * 60)
    obs_env = F1RaceSimulator()
    obs, _  = obs_env.reset()

    total_pit_laps = []

    for lap in range(1, obs_env.total_laps + 1):
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, done, _, info = obs_env.step(int(action))

        if int(action) > 0 or lap % 10 == 0:
            cname      = COMPOUND_NAMES.get(info['compound'], '?')
            cliff      = info.get('cliff_lap', 28)
            rival_a    = info.get('rival_ahead_age', '?')
            rival_b    = info.get('rival_behind_age', '?')
            stuck      = info.get('laps_stuck', 0)
            grain      = "⚠️GRAIN" if info.get('graining') else ""
            vsc        = "VSC" if info.get('vsc_active') else ""
            sc         = "SC" if info.get('sc_active') else ""
            rain       = f"rain:{info.get('rain_prob',0):.0%}" \
                         if info.get('rain_prob', 0) > 0.3 else ""
            flags      = " ".join(f for f in [grain, vsc, sc, rain] if f)

            print(
                f"  Lap {lap:2d} | {ACTION_NAMES[int(action)]} | "
                f"Tire:{info['tire_age']:2d}/{cliff} | {cname:6s} | "
                f"P{info['position']:2d} | "
                f"Rival fwd:{rival_a:2} bk:{rival_b:2} | "
                f"Stuck:{stuck} | Stops:{info['pit_count']} "
                f"{flags}"
            )

            if int(action) > 0:
                total_pit_laps.append(lap)

        if done:
            break

    print(f"\n{'='*60}")
    print(f"Final position:   P{info['position']}")
    print(f"Total pit stops:  {info['pit_count']}")
    print(f"Pit laps:         {total_pit_laps}")

    if info['pit_count'] == 0:
        print("⚠️  Never pitted — reward tuning needed")
    elif 1 <= info['pit_count'] <= 3:
        print("✅ Pit count realistic (1-3 stops expected)")
    else:
        print("⚠️  Too many stops")

    print(f"\n{'='*60}")
    print("WHAT THE AGENT NOW CONSIDERS:")
    print("  ✅ Tire age vs compound-specific cliff")
    print("  ✅ Gap to car behind (undercut threat)")
    print("  ✅ Gap to car ahead (overcut opportunity)")
    print("  ✅ Rival ahead/behind tire age and compound")
    print("  ✅ Whether rival ahead is near their cliff")
    print("  ✅ Laps stuck in traffic")
    print("  ✅ Overtaking difficulty of circuit")
    print("  ✅ Safety car probability and SC/VSC events")
    print("  ✅ Free pit window under SC (5.5s) vs VSC (10s) vs normal (22s)")
    print("  ✅ Rain probability")
    print("  ✅ Graining detection")
    print("  ✅ Rival covering strategy (if we pit, they may too)")
    print("  ✅ Pit timing quality (too early vs right window vs past cliff)")
    print("  ✅ Stop count management (penalizes excessive stops)")
    print("  ✅ Driver tire management rating (affects cliff timing)")

    env.close()
    return model


if __name__ == "__main__":
    train_agent()