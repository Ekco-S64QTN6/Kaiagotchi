# Operator hardware smoke-test checklist

This is a short **passive-capture startup and shutdown** check for a Linux host
with a dedicated monitor-mode wireless adapter. Use it before a first live
session or after a driver, kernel, `aircrack-ng`, or wireless-interface change.

**Authorization and safety:** run only on networks you own or are explicitly
authorized in writing to test. This checklist does not test injection, deauthentication,
or other active operations. It does not make Kaiagotchi a production security product.
Captured traffic and its identifiers are sensitive; keep logs and capture archives
private and never attach real captures to a bug report.

## 1. Confirm the host and tools

Run these as the operator first:

```bash
python3 --version
for tool in ip iw airodump-ng timeout; do
    command -v "$tool" || printf 'MISSING: %s\n' "$tool"
done
ip -brief link
iw dev
iw list | sed -n '/Supported interface modes:/,/Band /p'
```

Use Python 3.11 or newer. The tool loop must find `ip`, `iw`, `airodump-ng`,
and `timeout`. In the `iw list` output, find a radio that lists `monitor` under
**Supported interface modes**. In `iw dev`, confirm that the dedicated capture
adapter is present and map its interface name to the right physical radio.

Kaiagotchi defaults to capture interface `wlan1`; set `KAIAGOTCHI_INTERFACE`
if your dedicated adapter has another name. The `main.iface` setting refers to
the primary/managed interface and is not the capture-interface override. Keep
the interface used for normal internet access in managed mode and do not select
it as the capture interface.

Check the selected adapter before changing it:

```bash
CAP_IF="${KAIAGOTCHI_INTERFACE:-wlan1}"
sudo -v
sudo ip link show dev "$CAP_IF"
sudo iw dev "$CAP_IF" info
```

Stop here if the interface is missing, the adapter does not support monitor mode,
the selected adapter is also your normal connection, or you cannot obtain the
required privileges. Do not guess another interface name.

## 2. Run a controlled startup check

Before starting, check for an existing capture process and make sure you know
which session owns it:

```bash
pgrep -af airodump-ng || true
```

Do not terminate unrelated capture sessions. Make sure the configured interface
is the dedicated adapter and you have permission to passively observe the test
environment.

From the repository root, start Kaiagotchi with its web UI disabled. The wrapper
runs with elevated privileges and preserves the explicit capture-interface override:

```bash
CAP_IF="${KAIAGOTCHI_INTERFACE:-wlan1}"
KAIAGOTCHI_INTERFACE="$CAP_IF" ./run_kaiagotchi.sh --no-web
```

Expected behavior:

- Startup does not report missing commands, permission errors, or failure to switch
  the selected adapter to monitor mode.
- The logs indicate that monitor mode was verified and the `airodump-ng` process
  was started.
- The terminal dashboard remains responsive. No active packet injection is needed
  for this smoke test.

If startup fails, capture the relevant **redacted log text** and stop there. Do not
repeat the start attempt while a previous capture process or private temporary
capture directory may remain.

## 3. Verify clean shutdown

Quit with `q` or `Ctrl-C` once the startup check has passed. Allow the application
to finish cleanup; do not repeatedly kill the process just because shutdown takes
a moment.

After the app exits, verify the capture process and interface state:

```bash
pgrep -af airodump-ng || true
sudo iw dev "$CAP_IF" info
ip -brief link show dev "$CAP_IF"
```

A clean result means:

- No `airodump-ng` process from this test remains. If the command lists a process,
  confirm its interface and owner before taking any action; other sessions may be valid.
- The selected capture interface is back in **managed** mode and is up.
- The application reports that monitoring stopped cleanly and does not report an
  unreaped child or failed interface restoration.
- The primary/managed adapter's state is unchanged.

Review the application log at the configured log location if the terminal output
did not show the full shutdown result. Treat a missing success message as an
unverified check, not a pass.

## 4. Recovery and failure criteria

Treat the smoke test as **failed / unresolved** if the child cannot be reaped,
the interface cannot be restored, or the application reports incomplete shutdown.

In particular, a message that the capture process could not be reaped means that it
may still be writing a PCAP. Do **not** switch that adapter to managed mode, remove
the preserved private capture directory, or start another capture session until the
child is confirmed stopped. Preserve diagnostic logs and investigate the process
state; do not use broad `pkill` commands that could terminate another operator's
capture.

If the capture child is confirmed stopped but the dedicated adapter remains in
monitor mode, restore only that adapter:

```bash
CAP_IF="${KAIAGOTCHI_INTERFACE:-wlan1}"
sudo ip link set dev "$CAP_IF" down
sudo iw dev "$CAP_IF" set type managed
sudo ip link set dev "$CAP_IF" up
if command -v nmcli >/dev/null 2>&1; then
    sudo nmcli device set "$CAP_IF" managed yes
fi
sudo iw dev "$CAP_IF" info
```

Do not run this restoration sequence while a capture process could still be active.
If a restore command fails, stop and investigate the driver/NetworkManager error
rather than reporting a successful smoke test.

## 5. Record the result without sensitive data

Record only:

- OS/kernel and Python versions;
- adapter model/driver and the interface name (omit its MAC address);
- whether the required commands were present and monitor mode was supported;
- startup result, clean-stop result, and any redacted error text.

Do not attach PCAP/PCAPNG files, BSSID/station inventories, SSIDs, credentials,
or unredacted logs. This checklist is intentionally manual: standard CI has no
physical adapter and cannot claim to validate hardware mode switching or RF capture.
