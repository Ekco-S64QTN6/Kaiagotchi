"""Wireless interface capability helpers backed by the Linux iw tool."""

import logging
import re
import subprocess

logger = logging.getLogger(__name__)

_WIPHY_RE = re.compile(r"^\s*wiphy\s+(\d+)\s*$", re.MULTILINE)
_FREQUENCY_RE = re.compile(r"^\s*\*\s+\d+\s+MHz\s+\[(\d+)\](.*)$")


def iface_channels(interface: str) -> list[int]:
    """Return channels supported and enabled for a wireless interface.

    The interface is resolved to its kernel Wiphy with an interface-info query.
    Channel entries are then read from that PHY's capability report. Entries
    marked disabled are excluded; DFS/no-IR annotations are retained because
    they remain capabilities relevant to passive monitoring.

    No guessed channel list is returned when the interface, Wiphy, or iw query
    is unavailable. In those cases this function logs a diagnostic and returns
    an empty list. Channel numbers are returned as a sorted unique list;
    overlapping numeric IDs across 2.4, 5, and 6 GHz are not band-qualified by
    this legacy API.
    """
    if (
        not isinstance(interface, str)
        or not interface
        or interface != interface.strip()
        or len(interface) > 15
        or interface.startswith("-")
        or any(character.isspace() or character == "/" for character in interface)
    ):
        logger.warning("Cannot query wireless channels for invalid interface name %r", interface)
        return []

    try:
        interface_info = subprocess.run(
            ["iw", "dev", interface, "info"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Could not inspect wireless interface %s: %s", interface, exc)
        return []

    if interface_info.returncode != 0:
        detail = (interface_info.stderr or "").strip()
        logger.warning(
            "Could not inspect wireless interface %s with iw%s",
            interface,
            f": {detail}" if detail else "",
        )
        return []

    wiphy_match = _WIPHY_RE.search(interface_info.stdout)
    if wiphy_match is None:
        logger.warning("iw did not report a Wiphy for wireless interface %s", interface)
        return []

    wiphy = wiphy_match.group(1)
    try:
        phy_info = subprocess.run(
            ["iw", "phy", f"phy{wiphy}", "info"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Could not inspect wireless PHY phy%s for %s: %s", wiphy, interface, exc)
        return []

    if phy_info.returncode != 0:
        detail = (phy_info.stderr or "").strip()
        logger.warning(
            "Could not inspect wireless PHY phy%s for %s%s",
            wiphy,
            interface,
            f": {detail}" if detail else "",
        )
        return []

    channels: set[int] = set()
    for line in phy_info.stdout.splitlines():
        match = _FREQUENCY_RE.match(line)
        if match is None:
            continue
        channel = int(match.group(1))
        annotations = match.group(2).casefold()
        if "disabled" not in annotations:
            channels.add(channel)

    return sorted(channels)
