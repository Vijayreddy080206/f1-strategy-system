import redis
import json
import subprocess
import sys
import os
import signal

try:
    r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    r.ping()
except Exception as e:
    print("❌ Cannot connect to Redis. Is the server running?")
    sys.exit()

pubsub = r.pubsub()
pubsub.subscribe('manager_control')

current_process = None

def kill_current_feed():
    """Mercilessly terminates any feed currently running to free up RAM."""
    global current_process
    if current_process is not None:
        print("🛑 Terminating active data feed...")
        current_process.kill() # Used kill() instead of terminate() for instant death
        current_process.wait()
        current_process = None
        r.delete('live_f1_state') # Clear old data so the React UI resets

# --- NEW CTRL+C HANDLER ---
def handle_shutdown(sig, frame):
    print("\n⚠️ CTRL+C DETECTED. Executing emergency shutdown...")
    kill_current_feed()
    print("✅ System cleanly shut down.")
    sys.exit(0)

# Bind the Ctrl+C event to our shutdown function
signal.signal(signal.SIGINT, handle_shutdown)

print("🤖 SYSTEM MANAGER ONLINE. Waiting for UI Commands... (Press Ctrl+C to quit)")

try:
    for message in pubsub.listen():
        if message['type'] == 'message':
            data = json.loads(message['data'])
            cmd = data.get('command')

            if cmd == 'START_REPLAY':
                kill_current_feed()
                print(f"▶️ LAUNCHING REPLAY FEED...")
                # Forces it to stay inside (venv)
                current_process = subprocess.Popen([sys.executable, 'src/replay_feed.py'])

            elif cmd == 'START_LIVE':
                kill_current_feed()
                print("🔴 LAUNCHING LIVE FEED...")
                current_process = subprocess.Popen([sys.executable, 'src/live_feed.py'])

            elif cmd == 'STOP':
                kill_current_feed()
                print("⏹️ ALL FEEDS KILLED. Standing by.")
                
except Exception as e:
    print(f"Manager Error: {e}")
    kill_current_feed()
    sys.exit(1)