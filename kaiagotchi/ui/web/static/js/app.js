/**
 * KAIAGOTCHI CYBER-DECK // MAIN APPLICATION CONTROLLER
 * WebSocket telemetry stream, auto-reconnect, and widget dispatch.
 */

document.addEventListener('DOMContentLoaded', () => {
  const $ = (id) => document.getElementById(id);
  const telemetry = new window.TelemetryController();
  const operative = new window.OperativeController();

  let channel = '--';
  const rateChart = new window.LineChart($('pkt-rate-canvas'), {
    color: '#3dff8a', autoMax: 1000, unit: 'pkt/s', label: 'pkt/s',
  });
  const totalSpark = new window.LineChart($('pkt-total-canvas'), {
    color: '#3dff8a', autoMax: 1, axes: false,
  });
  const rssiChart = new window.LineChart($('rssi-history-canvas'), {
    color: '#00f0ff', yMin: -90, yMax: -30, yTicks: [-30, -50, -70, -90], unit: 'dBm',
    tickFormat: (v) => `${v}`, valueFormat: (v) => `${Math.round(v)}`,
    label: () => `Channel ${channel} RSSI (dBm)`,
  });

  const fmtNum = (v) => (typeof v === 'number' ? v.toLocaleString() : '--');
  const setText = (id, text) => { const el = $(id); if (el) el.textContent = text; };

  let lastTotals = null;

  function handle(snap) {
    if (!snap || snap.action === 'pong') return;

    setText('val-aps', `${snap.aps_count ?? 0} (${snap.aps_total ?? snap.aps_count ?? 0})`);
    setText('val-pwnd', `${snap.pwnd_count ?? 0}`);
    if (snap.mood) setText('val-mood', snap.mood.charAt(0).toUpperCase() + snap.mood.slice(1));
    setText('val-mode', snap.mode || '--');
    setText('val-uptime', snap.uptime || '--:--:--');
    setText('ap-count-label', `${snap.aps_count ?? 0} APs in range`);

    telemetry.updateAps(snap.aps || []);
    telemetry.updateStations(snap.stations || []);
    telemetry.updateChatter(snap.chatter || []);

    // Packet categories: '--' when the backend reports no breakdown.
    const pb = snap.packet_breakdown || {};
    for (const key of ['probe_req', 'beacon', 'auth', 'eapol']) {
      const id = key === 'probe_req' ? 'probe' : key;
      const row = pb[key];
      setText(`val-${id}-rx`, row ? `${fmtNum(row.rx)}/s` : '--');
      setText(`val-${id}-tx`, row ? `${fmtNum(row.tx)}/s` : '--');
    }

    const now = Date.now() / 1000;  // client clock: immune to server/viewer clock skew
    if (typeof snap.packet_rate === 'number') rateChart.push(snap.packet_rate, now);
    const avg = rateChart.average();
    const avgText = avg === null ? '--' : avg >= 1000 ? `${(avg / 1000).toFixed(1)}K` : `${Math.round(avg)}`;
    setText('pkt-rate-avg', `${avgText} pkt/s avg`);

    const tot = snap.total_packets;
    if (tot && typeof tot.rx === 'number' && typeof tot.tx === 'number') {
      setText('val-total-rx', fmtNum(tot.rx));
      setText('val-total-tx', fmtNum(tot.tx));
      // Sample the aggregate rate about once a second (connect bursts arrive ms apart).
      if (!lastTotals) {
        lastTotals = { sum: tot.rx + tot.tx, t: now };
      } else if (now - lastTotals.t >= 1) {
        const rate = (tot.rx + tot.tx - lastTotals.sum) / (now - lastTotals.t);
        if (rate >= 0) totalSpark.push(rate, now);
        lastTotals = { sum: tot.rx + tot.tx, t: now };
      }
    }

    channel = snap.current_channel ?? '--';
    if (typeof snap.current_rssi === 'number') rssiChart.push(snap.current_rssi, now);

    operative.updateState(snap);
  }

  // WebSocket with backoff reconnect
  let attempts = 0;
  function connect() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/ws`);
    ws.onopen = () => {
      attempts = 0;
      setText('hud-status', 'PASSIVE MONITORING');
      operative.setLink(true);
    };
    ws.onmessage = (ev) => {
      try {
        handle(JSON.parse(ev.data));
      } catch (err) {
        console.error('[CyberDeck] bad telemetry payload:', err);
      }
    };
    ws.onclose = () => {
      setText('hud-status', 'LINK LOST — RECONNECTING');
      operative.setLink(false);
      attempts++;
      setTimeout(connect, Math.min(4000, 500 * Math.pow(1.5, attempts)));
    };
    ws.onerror = () => ws.close();
  }
  connect();
});
