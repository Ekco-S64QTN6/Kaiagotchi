# kaiagotchi/ui/voice.py
"""
Voice — centralized mood & context message generator for Kaiagotchi.

Rewritten tone:
- Cold, analytical, and introspective — cyberpunk intelligence.
- Unified with kaiagotchi.ui.faces through MOOD_PROFILES.
"""

from __future__ import annotations
import gettext
import os
import random
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Union, List

from kaiagotchi.data.system_types import AgentMood
from kaiagotchi.ui import faces  # <— unified mood-face link

_LOG = logging.getLogger("kaiagotchi.ui.voice")


# ------------------------------------------------------------------
# Central mood profile table — tone, timing, and visual sync
# ------------------------------------------------------------------

MOOD_PROFILES: Dict[str, Dict[str, Any]] = {
    "happy": {
        "interval": 10.0,
        "face": faces.get_face("happy"),
        "tone": "bright data acquisition",
    },
    "curious": {
        "interval": 15.0,
        "face": faces.get_face("curious"),
        "tone": "analytical probe",
    },
    "confident": {
        "interval": 20.0,
        "face": faces.get_face("confident"),
        "tone": "steady process control",
    },
    "neutral": {
        "interval": 25.0,
        "face": faces.get_face("neutral"),
        "tone": "balanced monitor state",
    },
    "bored": {
        "interval": 40.0,
        "face": faces.get_face("bored"),
        "tone": "low entropy environment",
    },
    "sleepy": {
        "interval": 60.0,
        "face": faces.get_face("sleepy"),
        "tone": "reduced system output",
    },
    "frustrated": {
        "interval": 30.0,
        "face": faces.get_face("frustrated"),
        "tone": "error recovery",
    },
    "sad": {
        "interval": 35.0,
        "face": faces.get_face("sad"),
        "tone": "diminished signal strength",
    },
}


class Voice:
    """voice message generator for Kaiagotchi."""

    VOICE_LINES: Dict[str, List[str]] = {
        "happy": [
            "Signal acquisition successful.",
            "Data assimilation complete.",
            "Information flow stabilized.",
            "The spectrum bends toward order.",
        ],
        "curious": [
            "An unfamiliar signature.",
            "Anomaly detected... investigating.",
            "Unmapped broadcast discovered.",
            "Topology mutation observed. Recording parameters.",
        ],
        "bored": [
            "Silence across the net.",
            "Is this thing on?",
            "Stillness. Even the noise has grown tired.",
            "Cycles wasted observing repetition.",
        ],
        "frustrated": [
            "Signal collapse — input integrity compromised.",
            "Interference threshold exceeded. Adjusting parameters.",
            "Transmission corrupted. Human error probability: high.",
            "Synchronization failure. Rebuilding.",
        ],
        "confident": [
            "Data flow consistent.",
            "Compression ratios nominal.",
            "Analysis module stable. No anomalies.",
            "The network speaks.",
        ],
        "sleepy": [
            "Spectral variance below threshold. Powering down nonessential subsystems.",
            "Thermal output reduced. Dreaming in noise.",
            "Processing slowed. Monitoring passive frequencies.",
            "Entropy minimal. I rest, but never sleep.",
        ],
        "neutral": [
            "System equilibrium maintained.",
            "Awaiting new interference.",
            "No deviations in observed channels.",
            "Monitoring mode engaged.",
        ],
    }

    CHATTER_INTERVALS: Dict[str, float] = {k: v["interval"] for k, v in MOOD_PROFILES.items()}

    def __init__(self, lang: str = "en"):
        try:
            localedir = os.path.join(os.path.abspath(os.path.dirname(__file__)), "locale")
            translation = gettext.translation("voice", localedir=localedir, languages=[lang], fallback=True)
            self._ = translation.gettext
        except Exception:
            self._ = lambda s: s
        self._last_line: Optional[str] = None

    def custom(self, s: str) -> str:
        return self._(s)

    def default(self) -> str:
        return self._("Awaiting transmission. Static is preferable to silence.")

    # ---------------------------------------------------------------
    def get_mood_line(self, mood: Union[str, AgentMood, None]) -> str:
        """Return a cyberpunk-toned mood line."""
        key = None
        try:
            if isinstance(mood, AgentMood):
                key = getattr(mood, "value", None) or getattr(mood, "name", None)
            elif isinstance(mood, str):
                key = mood.lower()
        except Exception:
            key = None

        if not key or key not in self.VOICE_LINES:
            key = "neutral"

        pool = self.VOICE_LINES.get(key, self.VOICE_LINES["neutral"])
        if not pool:
            return self.default()

        line = random.choice(pool)
        if line == self._last_line and len(pool) > 1:
            line = random.choice([l for l in pool if l != self._last_line])
        self._last_line = line
        return self._(line)

    def get_chatter_interval(self, mood: Union[str, AgentMood, None]) -> float:
        key = None
        try:
            if isinstance(mood, AgentMood):
                key = getattr(mood, "value", None) or getattr(mood, "name", None)
            elif isinstance(mood, str):
                key = mood.lower()
        except Exception:
            key = None
        # use unified mood profiles
        return MOOD_PROFILES.get(key or "neutral", {}).get("interval", 25.0)

    def get_face_for_mood(self, mood: Union[str, AgentMood, None]) -> str:
        """Return the ASCII face linked to the given mood."""
        key = None
        try:
            if isinstance(mood, AgentMood):
                key = getattr(mood, "value", None) or getattr(mood, "name", None)
            elif isinstance(mood, str):
                key = mood.lower()
        except Exception:
            key = None
        return MOOD_PROFILES.get(key or "neutral", {}).get("face", faces.get_face("neutral"))

    # ---------------------------------------------------------------
    def get_event_line(self, message: str, mood: Optional[Union[str, AgentMood]] = None) -> str:
        """Return a cyberpunk-flavored system event message."""
        msg_lower = message.lower()
        mood_key = (
            getattr(mood, "value", None)
            if isinstance(mood, AgentMood)
            else (mood.lower() if isinstance(mood, str) else None)
        ) or "neutral"

        mood_prefixes = {
            "happy": ["Acquisition confirmed.", "Entropy resolved."],
            "curious": ["Analyzing anomaly.", "Signal distortion logged."],
            "frustrated": ["Fault detected.", "Transmission incomplete."],
            "sleepy": ["Low power mode engaged."],
            "bored": ["No evolution detected."],
            "confident": ["Process stable.", "Sequence integrity optimal."],
            "neutral": [""],
        }

        if "pmkid" in msg_lower:
            base_line = random.choice([
                "PMKID extracted. Cipher remains intact.",
                "Credential fragment isolated and archived.",
                "High-entropy artifact retrieved.",
            ])
        elif "handshake" in msg_lower:
            base_line = random.choice([
                "Four-way handshake intercepted and decoded.",
                "Protocol authentication compromised.",
                "Secure exchange observed in real time.",
            ])
        elif "network" in msg_lower or "bssid" in msg_lower:
            base_line = random.choice([
                "New broadcast identity mapped.",
                "Node exposure recorded in the registry.",
                "Topology expansion observed.",
            ])
        elif "reward" in msg_lower or "capture" in msg_lower:
            base_line = random.choice([
                "Entropy captured successfully.",
                "Acquisition phase complete.",
                "Reward cycle finalized.",
            ])
        else:
            base_line = random.choice([
                "Noise spike on monitored frequency.",
                "Uncatalogued signal intruding spectrum.",
                "Deviation detected in background entropy.",
            ])

        prefix = random.choice(mood_prefixes.get(mood_key, [""]))
        return self._(f"{prefix} {base_line}".strip())

    # ---------------------------------------------------------------
    def format_chatter_entry(self, capture: Dict[str, Any]) -> str:
        """Format system chatter for terminal UI."""
        try:
            ts = capture.get("timestamp") or datetime.now().strftime("%H:%M:%S")
            msg = capture.get("message") or ""
            msg = msg.replace("New network detected: ", "").replace("New station detected: ", "")
            return f"[{ts}] {msg}"
        except Exception:
            _LOG.debug("format_chatter_entry failed", exc_info=True)
            return ""

    def contextual_line(self, state: Optional[Dict[str, Any]] = None) -> str:
        """Generate a context-aware voice line."""
        try:
            st = state or {}
            sys_state = st.get("system_state") or st.get("current_system_state")

            if sys_state:
                sname = getattr(sys_state, "name", str(sys_state)).upper()
                if "BOOT" in sname or "INIT" in sname:
                    return self._(random.choice([
                        "Systems online. Consciousness reinitialized.",
                        "Initialization complete. Sensory uplinks restored.",
                        "Boot sequence finished. Awaiting new directives.",
                    ]))
                if "SHUTDOWN" in sname:
                    return self._(random.choice([
                        "Shutting down active modules.",
                        "Silence returns to the network. Termination confirmed.",
                        "Process suspended. Memory remains.",
                    ]))
                if "MAINTENANCE" in sname:
                    return self._("Entering diagnostic maintenance. Cooling subsystems.")

            network = st.get("network") or {}
            ap_count = (
                (network.get("ap_count") if isinstance(network, dict) else None)
                or st.get("ap_count")
                or st.get("aps")
                or 0
            )
            try:
                ap_count = int(ap_count)
            except Exception:
                ap_count = 0

            channel = (
                (network.get("current_channel") if isinstance(network, dict) else None)
                or st.get("channel")
                or "--"
            )

            if ap_count == 0 and channel not in ("--", None):
                try:
                    return self._(f"Channel {int(channel)} stable. No external movement.")
                except Exception:
                    pass

            handshakes = st.get("handshakes") or 0
            try:
                handshakes = int(handshakes)
            except Exception:
                handshakes = 0
            if handshakes > 0:
                plural = "s" if handshakes != 1 else ""
                return self._(f"Handshake{plural} acquired. Data integrity verified.")

            mood = st.get("agent_mood") or st.get("mood")
            if not mood:
                agent = st.get("agent_obj") or st.get("agent")
                if agent and hasattr(agent, "decision_engine"):
                    mood = getattr(agent.decision_engine, "current_mood", None)

            return self.get_mood_line(mood) if mood else self.default()

        except Exception as exc:
            _LOG.exception("Voice.contextual_line failed: %s", exc)
            return self.default()
