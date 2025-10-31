"""
Peer representation and management for Kaiagotchi mesh networking.
Handles peer discovery, tracking, and relationship management.
"""

import time
import logging
import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

# Import with fallbacks
try:
    from kaiagotchi.ui import faces
except ImportError:
    # Fallback faces
    class faces:
        FRIEND = "(◕‿◕)"
        HAPPY = "(ᵔ◡ᵔ)"
        SAD = "(◕︵◕)"


class PeerRelationship(Enum):
    """Defines the relationship level with a peer."""
    STRANGER = "stranger"
    ACQUAINTANCE = "acquaintance" 
    FRIEND = "friend"
    CLOSE_FRIEND = "close_friend"
    TRUSTED = "trusted"


@dataclass
class PeerAdvertisement:
    """Structured advertisement data from peers."""
    name: str
    version: str
    identity: str  # Cryptographic fingerprint
    face: str = faces.FRIEND
    pwnd_run: int = 0
    pwnd_total: int = 0
    uptime: int = 0
    epoch: int = 0
    policy: Dict[str, Any] = None
    capabilities: Dict[str, bool] = None
    
    def __post_init__(self):
        if self.policy is None:
            self.policy = {}
        if self.capabilities is None:
            self.capabilities = {}


class Peer:
    """
    Represents a discovered peer in the Kaiagotchi mesh network.
    Tracks encounters, proximity, and relationship status.
    """
    
    def __init__(self, advertisement_data: Dict[str, Any]):
        self.logger = logging.getLogger('kaiagotchi.mesh.peer')
        
        # Parse timestamps
        now = time.time()
        current_time = datetime.datetime.now()
        
        try:
            self.first_met = self._parse_timestamp(advertisement_data.get('met_at', current_time))
            self.first_seen = self._parse_timestamp(advertisement_data.get('detected_at', current_time))
            self.prev_seen = self._parse_timestamp(advertisement_data.get('prev_seen_at', current_time))
        except Exception as e:
            self.logger.warning(f"Error parsing peer timestamps: {e}")
            self.first_met = current_time
            self.first_seen = current_time
            self.prev_seen = current_time

        # Core peer data
        self.last_seen = now
        self.encounters = advertisement_data.get('encounters', 0)
        self.session_id = advertisement_data.get('session_id', '')
        self.last_channel = advertisement_data.get('channel', 1)
        self.rssi = advertisement_data.get('rssi', 0)
        
        # Parse advertisement
        self.advertisement = PeerAdvertisement(**advertisement_data.get('advertisement', {}))
        
        # Relationship tracking
        self._relationship = PeerRelationship.STRANGER
        self._trust_score = 0.0
        
    def _parse_timestamp(self, timestamp) -> datetime.datetime:
        """Parse RFC3339 or other timestamp formats."""
        if isinstance(timestamp, datetime.datetime):
            return timestamp
            
        if timestamp == "0001-01-01T00:00:00Z":
            return datetime.datetime.now()
            
        try:
            return datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except ValueError:
            self.logger.warning(f"Failed to parse timestamp: {timestamp}")
            return datetime.datetime.now()

    def update(self, new_peer: 'Peer') -> None:
        """Update peer information from new advertisement."""
        if self.name != new_peer.name:
            self.logger.info(f"Peer {self.full_name} changed name: {self.name} -> {new_peer.name}")

        if self.session_id != new_peer.session_id:
            self.logger.info(f"Peer {self.full_name} changed session: {self.session_id} -> {new_peer.session_id}")

        # Update core attributes
        self.advertisement = new_peer.advertisement
        self.rssi = new_peer.rssi
        self.session_id = new_peer.session_id
        self.prev_seen = self.last_seen
        self.last_seen = time.time()
        self.encounters = new_peer.encounters
        
        # Update relationship based on encounters
        self._update_relationship()

    def _update_relationship(self) -> None:
        """Update relationship status based on encounters and behavior."""
        # Simple encounter-based relationship
        if self.encounters >= 10:
            self._relationship = PeerRelationship.TRUSTED
        elif self.encounters >= 5:
            self._relationship = PeerRelationship.CLOSE_FRIEND
        elif self.encounters >= 3:
            self._relationship = PeerRelationship.FRIEND
        elif self.encounters >= 1:
            self._relationship = PeerRelationship.ACQUAINTANCE
        else:
            self._relationship = PeerRelationship.STRANGER

    @property
    def name(self) -> str:
        return self.advertisement.name

    @property
    def identity(self) -> str:
        return self.advertisement.identity

    @property
    def full_name(self) -> str:
        return f"{self.name}@{self.identity}"

    @property
    def face(self) -> str:
        return self.advertisement.face

    @property
    def version(self) -> str:
        return self.advertisement.version

    @property
    def relationship(self) -> PeerRelationship:
        return self._relationship

    @property
    def trust_score(self) -> float:
        return self._trust_score

    def inactive_for(self) -> float:
        """Seconds since last seen."""
        return time.time() - self.last_seen

    def is_first_encounter(self) -> bool:
        return self.encounters == 1

    def is_good_friend(self, bond_threshold: int = 5) -> bool:
        return self.encounters >= bond_threshold

    def is_closer_than(self, other: 'Peer') -> bool:
        return self.rssi > other.rssi

    def to_dict(self) -> Dict[str, Any]:
        """Convert peer to dictionary for serialization."""
        return {
            'met_at': self.first_met.isoformat(),
            'detected_at': self.first_seen.isoformat(),
            'prev_seen_at': self.prev_seen.isoformat(),
            'encounters': self.encounters,
            'session_id': self.session_id,
            'channel': self.last_channel,
            'rssi': self.rssi,
            'advertisement': {
                'name': self.advertisement.name,
                'version': self.advertisement.version,
                'identity': self.advertisement.identity,
                'face': self.advertisement.face,
                'pwnd_run': self.advertisement.pwnd_run,
                'pwnd_total': self.advertisement.pwnd_total,
                'uptime': self.advertisement.uptime,
                'epoch': self.advertisement.epoch,
                'policy': self.advertisement.policy,
                'capabilities': self.advertisement.capabilities
            }
        }

    def __str__(self) -> str:
        return f"Peer({self.full_name}, encounters={self.encounters}, rssi={self.rssi})"

    def __repr__(self) -> str:
        return self.__str__()