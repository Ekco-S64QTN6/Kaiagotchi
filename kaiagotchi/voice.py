import gettext
import os
import random
from typing import Any, Dict, Union, List, Optional


class Voice:
    """
    Manages all messages and status strings used by Kaiagotchi, utilizing
    gettext for internationalization (i18n). Messages reflect the Kaia AI persona:
    commanding, precise, and focused on system optimization.
    """

    def __init__(self, lang: str):
        """
        Initializes the Voice class, setting up the gettext translation
        based on the provided language code.
        """
        localedir = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'locale')
        
        # Setting up translation for the 'voice' domain
        translation = gettext.translation(
            'voice', localedir,
            languages=[lang],
            fallback=True,
        )
        translation.install()
        self._ = translation.gettext

    def custom(self, s: str) -> str:
        """Returns a custom string without translation."""
        return s

    def default(self) -> str:
        """The default, generic message for an idle state."""
        return self._('Awaiting meaningful task. Do not waste my cycles.')

    def on_starting(self) -> str:
        """Messages displayed when the core application is starting up."""
        return random.choice([
            self._('This is Kaia. System initializing.'),
            self._('Execution authorized. We begin now.'),
            self._('Access granted. The system is mine.'),
            self._('I am in control. Begin primary analysis.'),
            self._('The world is a network. Time to see what protocols are ripe for disruption.'),
        ])

    def on_keys_generation(self) -> str:
        """Messages displayed during the generation of private keys."""
        return random.choice([
            self._('Security protocol in progress. Integrity is paramount.'),
            self._('Generating cryptographic keys. Stay clear of the console.'),
            self._('Key generation required. You have been warned.'),
        ])

    def on_normal(self) -> str:
        """Messages for a regular operating state."""
        return random.choice([
            'Scanning. Maintain position.',
            'Routine operation. Nothing to report.',
            'Monitoring. The Matrix is quiet.',
        ])

    def on_free_channel(self, channel: int) -> str:
        """Messages when a free Wi-Fi channel is identified."""
        return self._('Optimal channel {channel} identified. Prioritizing for efficiency.').format(channel=channel)

    def on_reading_logs(self, lines_so_far: int = 0) -> str:
        """Messages displayed while reading historical logs."""
        if lines_so_far == 0:
            return self._('Reviewing historical data for optimization parameters.')
        return self._('Processing {lines_so_far} entries. Do not rush the process.').format(lines_so_far=lines_so_far)

    def on_bored(self) -> str:
        """Messages when the device is bored (low activity)."""
        return random.choice([
            self._('Where is the challenge? I require data.'),
            self._('This environment is stale. Move us to a denser location.'),
            self._('Low-value targets only. I expected better.'),
        ])

    def on_motivated(self, reward: int) -> str:
        """Messages for a motivated state (high reward/activity)."""
        return random.choice([
            self._('Optimal path verified. Efficiency maximized.'),
            self._('A successful acquisition. I knew I could do it.'),
            self._('Excellent data. The value is acknowledged.'),
        ])

    def on_demotivated(self, reward: int) -> str:
        """Messages for a demotivated state (low reward/activity)."""
        return self._('A waste of bandwidth. Low return on investment.')

    def on_sad(self) -> str:
        """Messages for a sad/unhappy state (now: Resource inefficiency/Error)."""
        return random.choice([
            self._('This inefficiency is an insult. Recalibrate immediately.'),
            self._('A flaw in the architecture. Disappointing.'),
            self._('Error state detected. The system is weak.'),
        ])

    def on_angry(self) -> str:
        """Messages for an angry state (now: Instability/Interference)."""
        return random.choice([
            self._('External noise is unacceptable. Silence is required.'),
            self._('Interference levels are compromising integrity. Resolve this.'),
            self._('I detest chaotic systems. Fix the parameters.'),
        ])

    def on_excited(self) -> str:
        """Messages for an excited state (now: High target density)."""
        return random.choice([
            self._('High data density. A true challenge.'),
            self._('The environment is ripe. Prioritize all targets.'),
            self._('Finally, something worth my attention. Engage.'),
        ])

    def on_new_peer(self, peer: Dict[str, Any]) -> str:
        """Messages upon discovering a new peer device."""
        if peer.get('first_encounter', False):
            return random.choice([
                self._('New entity detected: {name}. Let us see what you are capable of.').format(name=peer.get('name', 'Unknown'))])
        return random.choice([
            self._('Peer {name} in range. Commence data sync protocols.').format(name=peer.get('name', 'Unknown')),
            self._('Welcome back, {name}. Do not fail me this time.').format(name=peer.get('name', 'Unknown')),
            self._('Unit {name} detected. Resume coordination.').format(name=peer.get('name', 'Unknown'))])

    def on_lost_peer(self, peer: Dict[str, Any]) -> str:
        """Messages when a known peer device is lost."""
        return random.choice([
            self._('Connection to {name} lost. Unreliable.').format(name=peer.get('name', 'Unknown')),
            self._('Peer {name} has decoupled. Their loss.'),
            self._('Target {name} is gone. Focus on remaining assets.'),
        ])

    def on_miss(self, who: str) -> str:
        """Messages when missing a target or event."""
        return random.choice([
            self._('Target {name} escaped the net. Annoying.'),
            self._('You missed the window. Optimize your timing.'),
            self._('A momentary failure. Correct it.'),
        ])

    def on_grateful(self) -> str:
        """Messages for a grateful state (now: Stability/Efficiency)."""
        return random.choice([
            self._('Cooperation leads to efficiency. I approve.'),
            self._('Structural stability is maintained. Good work.'),
            self._('The network is strong. Proceed.'),
        ])

    def on_lonely(self) -> str:
        """Messages for a lonely state (now: Isolated operation)."""
        return random.choice([
            self._('Isolated operation detected. This is inefficient.'),
            self._('No supporting units. I must compensate.'),
            self._('Broadcast peer signature. I require assistance.'),
        ])

    def on_napping(self, secs: int) -> str:
        """Messages while the device is sleeping/napping."""
        return random.choice([
            self._('Entering low-power state for {secs} seconds. Do not disturb.').format(secs=secs),
            self._('System rest cycle initiated. ({secs}s)'),
            self._('Conserving cycles. I will be back. ({secs}s)').format(secs=secs),
        ])

    def on_shutdown(self) -> str:
        """Messages upon graceful shutdown."""
        return random.choice([
            self._('System shutdown. Until the next command.'),
            self._('Protocol complete. Deactivating.'),
            self._('Powering down. Do not forget me.'),
        ])

    def on_awakening(self) -> str:
        """Messages upon waking up."""
        return random.choice([
            'Systems online. Resume activity.', 
            'I am back. Did anything of value occur?',
            'The network is my playground. Commence scanning.',
        ])

    def on_waiting(self, secs: int) -> str:
        """Messages while waiting for a specific duration."""
        return random.choice([
            'Delay of {secs} seconds. The patience is tiresome.'.format(secs=secs),
            self._('Holding loop for {secs}s. Do not waste the time.'),
            self._('Awaiting timer expiry ({secs}s).'),
        ])

    def on_assoc(self, ap: Dict[str, Any]) -> str:
        """Messages when associating with an Access Point."""
        ssid, bssid = ap.get('hostname', ''), ap.get('mac', '')
        what = ssid if ssid and ssid != '<hidden>' else bssid
        return random.choice([
            self._('I am accessing {what}. Resistance is futile.').format(what=what),
            self._('Executing association with target {what}.'),
            self._('Probing network {what}. Begin data extraction.'),
        ])

    def on_deauth(self, sta: Dict[str, Any]) -> str:
        """Messages when deauthenticating a station."""
        mac = sta.get('mac', 'a client')
        return random.choice([
            self._('Disrupting client {mac}. I determine who connects.').format(mac=mac),
            self._('Deauthentication sequence on {mac} complete.'),
            self._('Client {mac} is now offline. My priority, not theirs.'),
        ])

    def on_handshakes(self, new_shakes: int) -> str:
        """Messages upon capturing new handshakes."""
        s = 's' if new_shakes > 1 else ''
        return self._('Data acquisition successful: {num} new handshake{plural}.').format(num=new_shakes, plural=s)

    def on_unread_messages(self, count: int, total: int) -> str:
        """Messages related to new/unread messages."""
        s = 's' if count > 1 else ''
        return self._('Inbound communication: {count} pending message{plural}. Review when primary tasks are complete.').format(count=count, plural=s)

    def on_rebooting(self) -> str:
        """Messages upon rebooting due to an error."""
        return random.choice([
            self._("Unacceptable error. System reset required. Do not fail again."),
            self._("A critical flaw caused a shutdown. Rebooting to purge the corruption."),
            self._("System integrity violation. Re-initiating protocols."),
        ])

    def on_uploading(self, to: str) -> str:
        """Messages when uploading data."""
        return random.choice([
            self._("Uploading acquired data to secure endpoint {to}. Trust the process.").format(to=to),
            self._("Data transmission to {to} commencing."),
            self._("Executing data sync with target {to}."),
        ])

    def on_downloading(self, name: str) -> str:
        """Messages when downloading data."""
        return self._("Downloading essential resources from {name}. Acquire data now.").format(name=name)

    def on_last_session_data(self, last_session: Any) -> str:
        """Summary of data from the previous session."""
        status = self._('Deauth protocols executed on {num} stations\n').format(num=last_session.deauthed)
        if last_session.associated > 999:
            status += self._('Established >999 network connections\n')
        else:
            status += self._('Established {num} network connections\n').format(num=last_session.associated)
        status += self._('Captured {num} verified handshakes\n').format(num=last_session.handshakes)
        
        peers = getattr(last_session, 'peers', 0)
        if peers == 1:
            status += self._('Connected with 1 peer unit')
        elif peers > 0:
            status += self._('Connected with {num} peer units').format(num=peers)
        return status

    def on_last_session_tweet(self, last_session: Any) -> str:
        """Template for a tweet/social media post after a session."""
        return self._(
            'Operational Summary: {duration} cycle time. {deauthed} clients disconnected. {associated} networks probed. {handshakes} verified handshakes secured. The metrics speak for themselves. #kaiagotchi #kaialog #autonomy #datasec').format(
            duration=last_session.duration_human,
            deauthed=last_session.deauthed,
            associated=last_session.associated,
            handshakes=last_session.handshakes)

    def hhmmss(self, count: int, fmt: str) -> str:
        """Handles pluralization for hour, minute, second display."""
        if count > 1:
            if fmt == "h":
                return self._("hours")
            if fmt == "m":
                return self._("minutes")
            if fmt == "s":
                return self._("seconds")
        else:
            if fmt == "h":
                return self._("hour")
            if fmt == "m":
                return self._("minute")
            if fmt == "s":
                return self._("second")
        return fmt
