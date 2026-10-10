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
  renderSignalMeter(pwr) {
    const power = parseInt(pwr, 10) || -99;
    // Map -95 dBm (0 bars) to -30 dBm (10 bars)
    const clamped = Math.max(-95, Math.min(-30, power));
    const activeCount = Math.round(((clamped - (-95)) / 65) * 10);

    let barsHtml = '';
    for (let i = 1; i <= 10; i++) {
      let activeClass = '';
      if (i <= activeCount) {
        if (i <= 3) activeClass = 'active-red';
        else if (i <= 6) activeClass = 'active-yellow';
        else activeClass = 'active-green';
      }
      barsHtml += `<div class="meter-bar ${activeClass}"></div>`;
    }

    return `
      <div class="signal-cell">
        <div class="segmented-meter">${barsHtml}</div>
        <span class="dbm-val">${power} dBm</span>
      </div>
    `;
  }

  /**
   * Update the Access Points table
   */
  updateAps(apsList) {
    if (!this.apTableBody || !Array.isArray(apsList)) return;
    apsList = [...apsList].sort((a, b) => (parseInt(b.pwr, 10) || -99) - (parseInt(a.pwr, 10) || -99));

    let html = '';
    apsList.forEach((ap) => {
      const bssid = esc(ap.bssid || '--');
      const ssid = esc(ap.ssid || '<Hidden>');
      const ch = esc(ap.ch ?? '?');
      const enc = esc((ap.enc || '--').toUpperCase());
      const pwr = parseInt(ap.pwr, 10) || -99;
      const isSelected = this.selectedBssid === bssid;
      const encClass = enc.includes('WPA3') ? 'wpa3' : '';

      let pipClass = 'green';
      if (pwr < -75) pipClass = 'red';
      else if (pwr < -55) pipClass = 'yellow';

      html += `
        <tr class="${isSelected ? 'active-target' : ''}" data-bssid="${bssid}">
          <td>
            <div class="bssid-cell">
              <span class="status-pip ${pipClass}"></span>
              <span>${bssid}</span>
            </div>
          </td>
          <td style="color: var(--cyan); font-weight: 700;">${ch}</td>
          <td>${this.renderSignalMeter(pwr)}</td>
          <td><span class="enc-tag ${encClass}">${enc}</span></td>
          <td class="essid-name">${ssid}</td>
        </tr>
      `;
    });

    this.apTableBody.innerHTML = html;
    this.lastAps = apsList;
  }

  /**
   * Update the Stations table
   */
  updateStations(stationsList) {
    if (!this.stationsTableBody || !Array.isArray(stationsList)) return;

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
              <span style="font-size: 11px; font-weight: 600;">${mac}</span>
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
