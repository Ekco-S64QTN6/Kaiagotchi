/**
 * KAIAGOTCHI CYBER-DECK // TELEMETRY WIDGET CONTROLLER
 * Renders AP table, Stations table, segmented signal bars, and System Chatter console.
 */

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));

class TelemetryController {
  constructor() {
    this.apTableBody = document.getElementById('ap-table-body');
    this.stationsTableBody = document.getElementById('stations-table-body');
    this.chatterTerminal = document.getElementById('chatter-terminal');
    this.selectedBssid = null;
    this.lastChatterHash = '';
    this.lastAps = [];

    if (this.apTableBody) {
      this.apTableBody.addEventListener('click', (e) => {
        const row = e.target.closest('tr[data-bssid]');
        if (!row) return;
        const bssid = row.getAttribute('data-bssid');
        this.selectedBssid = this.selectedBssid === bssid ? null : bssid;
        this.updateAps(this.lastAps);
      });
    }
  }

  /**
   * Render discrete 10-bar LED signal meter with dBm readout
   */
  /** The class of each of the meter's ten bars for a signal in dBm. */
  meterBars(pwr) {
    const power = parseInt(pwr, 10) || -99;
    // Map -95 dBm (0 bars) to -30 dBm (10 bars)
    const clamped = Math.max(-95, Math.min(-30, power));
    const activeCount = Math.round(((clamped - (-95)) / 65) * 10);
    const out = [];
    for (let i = 1; i <= 10; i++) {
      out.push(i > activeCount ? '' : i <= 3 ? 'active-red' : i <= 6 ? 'active-yellow' : 'active-green');
    }
    return out;
  }

  renderSignalMeter(pwr) {
    const power = parseInt(pwr, 10) || -99;
    const barsHtml = this.meterBars(power).map((c) => `<div class="meter-bar ${c}"></div>`).join('');

    return `
      <div class="signal-cell">
        <div class="segmented-meter">${barsHtml}</div>
        <span class="dbm-val">${power} dBm</span>
      </div>
    `;
  }

  /**
   * Update the Access Points table.
   *
   * Snapshots arrive at 10 Hz but the AP list changes about once a second (each
   * airodump CSV read), and rebuilding up to 200 rows with innerHTML on every
   * message kept the main thread busy under the codec's frames. An unchanged
   * snapshot is skipped; otherwise each row is kept per BSSID and only the
   * cells whose values changed are touched. The markup is the same as before.
   */
  updateAps(apsList) {
    if (!this.apTableBody || !Array.isArray(apsList)) return;
    apsList = [...apsList].sort((a, b) => (parseInt(b.pwr, 10) || -99) - (parseInt(a.pwr, 10) || -99));
    this.lastAps = apsList;

    const key = (this.selectedBssid || '') + '\n' + apsList
      .map((ap) => `${ap.bssid}|${ap.ssid}|${ap.ch}|${ap.enc}|${parseInt(ap.pwr, 10) || -99}`).join('\n');
    if (key === this.lastApsKey) return;
    this.lastApsKey = key;

    if (!this.apRows) this.apRows = new Map();
    const seen = new Set();
    let index = 0;
    for (const ap of apsList) {
      const bssid = String(ap.bssid || '--');
      if (seen.has(bssid)) continue;          // a duplicated BSSID renders once
      seen.add(bssid);
      let row = this.apRows.get(bssid);
      if (!row) {
        row = this._createApRow(bssid);
        this.apRows.set(bssid, row);
      }
      this._fillApRow(row, ap);
      const at = this.apTableBody.children[index];
      if (at !== row.tr) this.apTableBody.insertBefore(row.tr, at || null);
      index++;
    }
    for (const [bssid, row] of this.apRows) {
      if (!seen.has(bssid)) {
        row.tr.remove();
        this.apRows.delete(bssid);
      }
    }
  }

  _createApRow(bssid) {
    const tmpl = document.createElement('tbody');
    tmpl.innerHTML = `
        <tr data-bssid="${esc(bssid)}">
          <td>
            <div class="bssid-cell">
              <span class="status-pip"></span>
              <span>${esc(bssid)}</span>
            </div>
          </td>
          <td style="color: var(--cyan); font-weight: 700;"></td>
          <td>${this.renderSignalMeter(-99)}</td>
          <td><span class="enc-tag"></span></td>
          <td class="essid-name"></td>
        </tr>`;
    const tr = tmpl.firstElementChild;
    const cells = tr.children;
    return {
      tr,
      pip: tr.querySelector('.status-pip'),
      ch: cells[1],
      bars: Array.from(tr.querySelectorAll('.meter-bar')),
      dbm: tr.querySelector('.dbm-val'),
      enc: tr.querySelector('.enc-tag'),
      ssid: cells[4],
      v: {},
    };
  }

  _fillApRow(row, ap) {
    const v = row.v;
    const set = (k, val, apply) => { if (v[k] !== val) { v[k] = val; apply(val); } };
    const pwr = parseInt(ap.pwr, 10) || -99;
    const enc = String(ap.enc || '--').toUpperCase();
    set('sel', this.selectedBssid === String(ap.bssid || '--'), (on) => { row.tr.className = on ? 'active-target' : ''; });
    set('pip', pwr < -75 ? 'red' : pwr < -55 ? 'yellow' : 'green', (c) => { row.pip.className = `status-pip ${c}`; });
    set('ch', String(ap.ch ?? '?'), (t) => { row.ch.textContent = t; });
    set('pwr', pwr, (p) => {
      const active = this.meterBars(p);
      row.bars.forEach((bar, i) => { bar.className = `meter-bar ${active[i]}`; });
      row.dbm.textContent = `${p} dBm`;
    });
    set('enc', enc, (e) => {
      row.enc.textContent = e;
      row.enc.className = `enc-tag ${e.includes('WPA3') ? 'wpa3' : ''}`;
    });
    set('ssid', String(ap.ssid || '<Hidden>'), (t) => { row.ssid.textContent = t; });
  }

  /**
   * Update the Stations table
   */
  updateStations(stationsList) {
    if (!this.stationsTableBody || !Array.isArray(stationsList)) return;
    const key = stationsList.slice(0, 10)
      .map((s) => `${s.mac}|${s.pwr}|${s.ch}|${s.tx_rx}|${s.status}`).join('\n');
    if (key === this.lastStationsKey) return;
    this.lastStationsKey = key;

    let html = '';
    stationsList.slice(0, 10).forEach((sta) => {
      const mac = esc(sta.mac || '--');
      const pwr = esc(sta.pwr ?? '-');
      const ch = esc(sta.ch || '-');
      const txRx = esc(sta.tx_rx || '-');
      const status = esc(sta.status || 'CONNECTED');
      let statusColor = 'var(--green)';
      let pipClass = 'green';

      if (status === 'HANDSHAKE') {
        statusColor = 'var(--yellow)';
        pipClass = 'yellow';
      } else if (status === 'PROBING') {
        statusColor = '#ff914d';
        pipClass = 'orange';
      } else if (status === 'DISCONNECTED') {
        statusColor = 'var(--red)';
        pipClass = 'red';
      }

      html += `
        <tr>
          <td>
            <div class="bssid-cell">
              <span class="status-pip ${pipClass}"></span>
              <span title="${mac}" style="font-size: 11px; font-weight: 600;">${mac}</span>
            </div>
          </td>
          <td style="color: var(--text-mid); font-weight: 600;">${pwr}</td>
          <td style="color: var(--cyan); font-weight: 700;">${ch}</td>
          <td style="color: var(--text-bright); font-size: 11px;">${txRx}</td>
          <td style="color: ${statusColor}; font-weight: 700; font-size: 10px;">${status}</td>
        </tr>
      `;
    });

    this.stationsTableBody.innerHTML = html;
  }

  /**
   * Update System Chatter log terminal with color-coded tags
   */
  updateChatter(chatterList) {
    if (!this.chatterTerminal || !Array.isArray(chatterList)) return;

    const chatterKey = chatterList.map((c) => (c.time || '') + (c.text || '')).join('|');
    if (chatterKey === this.lastChatterHash) return;
    this.lastChatterHash = chatterKey;

    let html = '';
    chatterList.slice(-40).forEach((entry) => {
      const time = esc(entry.time || '');
      const text = esc(entry.text || '');
      let type = (entry.type || 'info').toLowerCase();

      // Guess type from text if generic
      if (type === 'info') {
        const upper = text.toUpperCase();
        if (upper.includes('HANDSHAKE') || upper.includes('PMKID')) type = 'eapol';
        else if (upper.includes('WARN') || upper.includes('FLUCTUATION')) type = 'warn';
        else if (upper.includes('AUTH') || upper.includes('ASSOCIAT')) type = 'auth';
        else if (upper.includes('DISCONNECTED') || upper.includes('SUCCESS')) type = 'success';
        else if (upper.includes('SYNC')) type = 'sync';
      }

      type = type.replace(/[^a-z]/g, '');
      const tagText = type.toUpperCase();
      const timeDisplay = time ? (time.startsWith('[') ? time : `[${time}]`) : '';

      html += `
        <div class="chatter-line">
          <span class="chatter-ts">${timeDisplay}</span>
          <span class="chatter-tag ${type}">${tagText}</span>
          <span class="chatter-text">${text}</span>
        </div>
      `;
    });

    // Re-append terminal prompt
    html += `
      <div class="terminal-prompt">
        <span>&gt;</span>
        <span class="terminal-cursor"></span>
      </div>
    `;

    this.chatterTerminal.innerHTML = html;
    this.chatterTerminal.scrollTop = this.chatterTerminal.scrollHeight;
  }
}

window.TelemetryController = TelemetryController;
