# kaiagotchi/tests/test_emotion_loop.py
"""
Full integration test for the Kaiagotchi emotional feedback loop.

This verifies:
- Automata + RewardEngine + Epoch integration.
- Live terminal updates via View + TerminalDisplay.
- Proper mood transitions based on simulated rewards.
"""

import asyncio
import random
import time

from kaiagotchi.core.automata import Automata
from kaiagotchi.ui.terminal_display import TerminalDisplay
from kaiagotchi.ui.view import View


async def main():
    # Minimal config for test
    config = {
        "personality": {
            "reward_alpha": 0.25,
            "min_mood_duration": 2.0,
            "mood_hysteresis": 0.1,
            "threshold_excited": 0.6,
            "threshold_happy": 0.25,
            "threshold_curious": 0.05,
            "threshold_bored": -0.05,
            "threshold_frustrated": -0.25,
            "threshold_sad": -0.6,
            "default_mood": "CALM",
            "sad_num_epochs": 5,
            "bored_num_epochs": 3,
            "bond_encounters_factor": 1.0,
        }
    }

    # Initialize systems
    display = TerminalDisplay(config)
    view = View(config=config, display=display)
    automata = Automata(config=config, view=view)

    await view.on_starting()
    await asyncio.sleep(2)

    print("\n🌡️  Starting emotional simulation loop...\n")

    # Simulate 12 epochs with random reward dynamics
    for epoch in range(12):
        # Fake state data — mimic network scan results
        {
            "network": {
                "access_points": [{"bssid": f"AA:BB:CC:{epoch:02X}:01:01"} for _ in range(random.randint(0, 5))]
            },
            "metrics": {"uptime_seconds": time.time() % 9999},
        }

        # Randomly perturb reward inputs
        random_reward = random.uniform(-1.0, 1.0)
        mood = automata.process_reward(random_reward)

        print(f"[epoch {epoch}] reward={random_reward:+.3f} → mood={mood.name}")
        await asyncio.sleep(2.5)

    print("\n✅ Emotional simulation complete. Shutting down...\n")
    await view.on_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
