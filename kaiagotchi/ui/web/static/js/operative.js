/**
 * KAIAGOTCHI CYBER-DECK // OPERATIVE VIEWPORT CONTROLLER
 * Bridges telemetry snapshots to the Kaia codec (js/kaia/*): mood changes,
 * new chatter lines (Kaia "transmits" them), passive-capture reactions, and
 * the CH / FREQ / signal readouts inside the frame.
 */

// Wi-Fi channel -> centre frequency (MHz).
function channelToMhz(ch) {
  const c = parseInt(ch, 10);
  if (!c) return null;
  if (c === 14) return 2484;
  if (c >= 1 && c <= 13) return 2407 + c * 5;
  if (c >= 32 && c <= 177) return 5000 + c * 5;
  return null;
}

class OperativeController {
  constructor() {
    this.stageEl = document.getElementById('kaia-operative-stage');
    this.chEl = document.getElementById('codec-ch');
    this.freqEl = document.getElementById('codec-freq');
    this.chBars = Array.from(document.querySelectorAll('#codec-bars i'));
    this.syncBars = Array.from(document.querySelectorAll('#sync-bars i'));
    this.syncEl = document.getElementById('kaia-sync-status');

    this.codec = null;
    this.pending = null;
    this.lastMood = null;
    this.lastStatus = null;
    this.lastPwnd = null;
    this.lastApCount = null;

    const hook = {
      stageElement: this.stageEl,
      setMood: (mood) => this.codec && this.codec.setMood(mood),
      react: (kind) => this.codec && this.codec.react(kind),
      // Optional external listeners; the codec reacts on its own either way.
      onMoodChange: null,
      onHandshakeCaptured: null,
    };
    window.KaiaOperative = hook;

    // Kaia's portrait is t2 (Kaiacord assets/kaia-avatar/portraits/t2), as in Kaia
    // Sentinel. ?face=<name> shows another (see KaiaCodec.PORTRAITS); ?face=random
    // rotates through all six.
    const face = new URLSearchParams(location.search).get('face') || 't2';
    // maxFps 120: the codec renders a frame only when a full interval has passed,
    // so the engine's default 60 landed on every second refresh of a 100 Hz
    // display (50 fps). A frame costs well under a millisecond, and the animation
    // is time-based, so rendering on each refresh up to 120 Hz is just smoother.
    window.KaiaCodec.mount(this.stageEl, { portrait: face, maxFps: 120 })
      .then((codec) => {
        this.codec = codec;
        if (this.pending) this.updateState(this.pending);
      })
      .catch((err) => console.error('[KaiaOperative] codec failed to mount:', err));
  }

  setLink(ok) {
    if (this.syncEl) {
      this.syncEl.textContent = ok ? 'OK' : 'LOST';
      this.syncEl.classList.toggle('retry', !ok);
    }
    if (this.codec) this.codec.setLink(ok);
  }

  updateState(payload) {
    if (!this.codec) {
      this.pending = payload;
      return;
    }

    const mood = String(payload.mood || 'neutral').toLowerCase();
    if (mood !== this.lastMood) {
      this.lastMood = mood;
      this.codec.setMood(mood);
      if (typeof window.KaiaOperative.onMoodChange === 'function') window.KaiaOperative.onMoodChange(mood, payload);
    }

    // New chatter line: Kaia transmits it (mouth flaps over the line length).
    if (payload.status && payload.status !== this.lastStatus) {
      if (this.lastStatus !== null) this.codec.speak(payload.status);
      this.lastStatus = payload.status;
    }

    // Passive handshake capture -> celebratory reaction.
    const pwnd = Number(payload.pwnd_count) || 0;
    if (this.lastPwnd !== null && pwnd > this.lastPwnd) {
      this.codec.react('capture');
      if (typeof window.KaiaOperative.onHandshakeCaptured === 'function') window.KaiaOperative.onHandshakeCaptured(payload);
    }
    this.lastPwnd = pwnd;

    const apCount = Number(payload.aps_count) || 0;
    if (this.lastApCount !== null && apCount > this.lastApCount) this.codec.react('discovery');
    this.lastApCount = apCount;

    const ch = payload.current_channel;
    const mhz = channelToMhz(ch);
    if (this.chEl) this.chEl.textContent = ch ?? '--';
    if (this.freqEl) this.freqEl.textContent = mhz ? `${(mhz / 1000).toFixed(3)} GHz` : '--';

    // Bars: strongest AP on the current channel (-90 dBm = 0, -40 dBm = 5).
    const onCh = (payload.aps || []).filter((a) => String(a.ch) === String(ch));
    const powers = onCh.map((a) => parseInt(a.pwr, 10)).filter((v) => v < 0 && v > -100);
    const best = powers.length ? Math.max(...powers) : -100;
    const lit = Math.round(Math.max(0, Math.min(1, (best + 90) / 50)) * 5);
    this.chBars.forEach((b, i) => b.classList.toggle('on', i < lit));
    this.syncBars.forEach((b, i) => b.classList.toggle('on', i < 5));
  }
}

window.OperativeController = OperativeController;
