"""
ProVisionGuard AI — Auto-Restart Watchdog
==========================================
This script runs app_v6.py and automatically restarts it
if it crashes or exits unexpectedly.

Usage:
    python run_pvg.py

Features:
  ✅ Auto-restart on crash
  ✅ Restart delay (5 seconds)
  ✅ Max restart limit (prevents infinite crash loop)
  ✅ Crash log saved to data/crash.log
  ✅ Ctrl+C to stop cleanly
"""

import subprocess, sys, time, os, signal
from datetime import datetime

APP       = "app_v6.py"
LOG_FILE  = "data/crash.log"
MAX_RESTARTS = 20
RESTART_DELAY = 5
RESET_WINDOW  = 300

os.makedirs("data", exist_ok=True)

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def main():
    restarts = 0
    last_start = None
    proc = None

    def handle_exit(sig, frame):
        print("\n\n🛑 Watchdog stopping (Ctrl+C)...")
        if proc and proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=5)
            except: proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    log("="*50)
    log("ProVisionGuard AI Watchdog Started")
    log(f"App: {APP}")
    log(f"Max restarts: {MAX_RESTARTS}")
    log("="*50)

    while True:
        if last_start and (time.time() - last_start) > RESET_WINDOW:
            if restarts > 0:
                log(f"[OK] Stable for {RESET_WINDOW}s -- reset crash counter")
            restarts = 0

        if restarts >= MAX_RESTARTS:
            log(f"[STOP] Max restarts ({MAX_RESTARTS}) reached. Stopping watchdog.")
            log("       Check data/crash.log for details.")
            break

        log(f"[START] Starting app_v6.py (attempt #{restarts+1})")
        last_start = time.time()

        try:
            proc = subprocess.Popen(
                [sys.executable, APP],
                stdout=sys.stdout,
                stderr=sys.stderr
            )
            exit_code = proc.wait()
        except FileNotFoundError:
            log(f"[ERROR] {APP} not found! Make sure app_v6.py exists.")
            break
        except Exception as e:
            log(f"[ERROR] Error launching app: {e}")
            exit_code = -1

        if exit_code == 0:
            log("[OK] App exited cleanly (exit code 0). Stopping watchdog.")
            break

        restarts += 1
        run_dur = int(time.time() - last_start)
        log(f"[CRASH] Exit code: {exit_code} | Ran for: {run_dur}s | Total restarts: {restarts}")

        if restarts < MAX_RESTARTS:
            log(f"[WAIT] Restarting in {RESTART_DELAY}s... (Press Ctrl+C to stop)")
            for i in range(RESTART_DELAY, 0, -1):
                print(f"\r  Restarting in {i}s...", end="", flush=True)
                time.sleep(1)
            print()

    log("Watchdog stopped.")

if __name__ == "__main__":
    main()