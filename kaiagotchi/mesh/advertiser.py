"""
Mesh network advertiser for Kaiagotchi peer-to-peer communication.
Handles peer discovery, advertisement, and proximity-based interactions.
"""

import threading
import logging
import time
from typing import Dict, Any, Optional, Set
from dataclasses import dataclass

# Import with fallbacks
try:
    from kaiagotchi import voice
    from kaiagotchi.ui import faces
    from kaiagotchi.plugins import manager as plugin_manager
    from kaiagotchi.mesh.peer import Peer, PeerRelationship
    from kaiagotchi.mesh import grid
except ImportError:
    logging.warning("Some mesh imports failed - using fallbacks")
    
    # Fallback implementations
    class voice:
        @staticmethod
        def get_peer_greeting(name):
            return f"Hello {name}!"
    
    class faces:
        FRIEND = "(◕‿◕)"
    
    class plugin_manager:
        @staticmethod
        def on(event, *args):
            pass
    
    class grid:
        @staticmethod
        def set_advertisement_data(data):
            pass
        
        @staticmethod
        def advertise(enabled):
            pass
        
        @staticmethod
        def peers():
            return []


@dataclass
class MeshConfig:
    """Configuration for mesh networking."""
    enabled: bool = True
    advertise: bool = True
    scan_interval: int = 3
    bond_encounters_factor: int = 5
    max_peers: int = 50


class MeshAdvertiser:
    """
    Manages peer discovery and advertisement in the Kaiagotchi mesh network.
    Handles peer lifecycle events and proximity-based interactions.
    """
    
    def __init__(self, config: Dict[str, Any], view=None, keypair=None):
        self.config = MeshConfig(**config.get('mesh', {}))
        self.view = view
        self.keypair = keypair
        self.logger = logging.getLogger('kaiagotchi.mesh.advertiser')
        
        # Peer management
        self.peers: Dict[str, Peer] = {}
        self.closest_peer: Optional[Peer] = None
        
        # Advertisement data
        self.advertisement = {
            'name': config.get('main', {}).get('name', 'Kaiagotchi'),
            'version': '1.0.0',  # Should come from package
            'identity': keypair.fingerprint if keypair else 'unknown',
            'face': faces.FRIEND,
            'pwnd_run': 0,
            'pwnd_total': 0,
            'uptime': 0,
            'epoch': 0,
            'policy': config.get('personality', {}),
            'capabilities': {
                'handshake_sharing': True,
                'cooperative_scanning': True,
                'data_sync': False
            }
        }
        
        # Thread management
        self._running = False
        self._advertise_thread: Optional[threading.Thread] = None
        
    def start(self) -> bool:
        """Start the mesh advertiser and peer discovery."""
        if not self.config.enabled:
            self.logger.warning("Mesh networking is disabled")
            return False
            
        if not self.config.advertise:
            self.logger.warning("Advertisement is disabled")
            return False
            
        try:
            self._running = True
            
            # Start advertisement thread
            self._advertise_thread = threading.Thread(
                target=self._advertisement_loop,
                name="MeshAdvertiser",
                daemon=True
            )
            self._advertise_thread.start()
            
            # Start peer discovery
            discovery_thread = threading.Thread(
                target=self._peer_discovery_loop,
                name="PeerDiscovery",
                daemon=True
            )
            discovery_thread.start()
            
            self.logger.info("Mesh advertiser started successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start mesh advertiser: {e}")
            return False
    
    def stop(self) -> None:
        """Stop the mesh advertiser."""
        self._running = False
        if self._advertise_thread:
            self._advertise_thread.join(timeout=5.0)
    
    def update_advertisement(self, updates: Dict[str, Any]) -> None:
        """Update advertisement data."""
        self.advertisement.update(updates)
        
        # Push updates to grid
        try:
            grid.set_advertisement_data(self.advertisement)
        except Exception as e:
            self.logger.warning(f"Failed to update grid advertisement: {e}")
    
    def _advertisement_loop(self) -> None:
        """Main advertisement loop."""
        # Initial delay to let system stabilize
        time.sleep(10)
        
        while self._running:
            try:
                # Update dynamic advertisement fields
                self._update_dynamic_fields()
                
                # Advertise presence
                grid.advertise(True)
                
                # Sleep before next update
                time.sleep(self.config.scan_interval)
                
            except Exception as e:
                self.logger.error(f"Error in advertisement loop: {e}")
                time.sleep(5)  # Brief pause before retry
    
    def _peer_discovery_loop(self) -> None:
        """Peer discovery and management loop."""
        while self._running:
            try:
                self._poll_peers()
                time.sleep(self.config.scan_interval)
                
            except Exception as e:
                self.logger.error(f"Error in peer discovery loop: {e}")
                time.sleep(5)
    
    def _update_dynamic_fields(self) -> None:
        """Update dynamic advertisement fields."""
        # This would update from system state
        # Example: self.advertisement['uptime'] = get_uptime()
        #          self.advertisement['epoch'] = get_current_epoch()
        pass
    
    def _poll_peers(self) -> None:
        """Poll for nearby peers and manage peer lifecycle."""
        try:
            grid_peers = grid.peers()
            current_peer_ids = set()
            
            # Reset closest peer
            self.closest_peer = None
            
            # Process discovered peers
            for peer_data in grid_peers:
                peer = Peer(peer_data)
                current_peer_ids.add(peer.identity)
                
                # Track closest peer by RSSI
                if self.closest_peer is None or peer.is_closer_than(self.closest_peer):
                    self.closest_peer = peer
                
                # Handle new peers
                if peer.identity not in self.peers:
                    self._handle_new_peer(peer)
                else:
                    # Update existing peer
                    self.peers[peer.identity].update(peer)
            
            # Handle lost peers
            lost_peers = set(self.peers.keys()) - current_peer_ids
            for peer_id in lost_peers:
                self._handle_lost_peer(self.peers[peer_id])
                del self.peers[peer_id]
                
        except Exception as e:
            self.logger.error(f"Error polling peers: {e}")
    
    def _handle_new_peer(self, peer: Peer) -> None:
        """Handle discovery of a new peer."""
        self.peers[peer.identity] = peer
        
        self.logger.info(f"New peer detected: {peer.full_name} (encounters: {peer.encounters})")
        
        # Notify view if available
        if self.view and hasattr(self.view, 'on_new_peer'):
            self.view.on_new_peer(peer)
        
        # Notify plugins
        plugin_manager.on('peer_detected', self, peer)
        
        # Voice greeting for close peers
        if peer.rssi > -50:  # Close proximity
            greeting = voice.get_peer_greeting(peer.name)
            self.logger.info(f"Greeting: {greeting}")
    
    def _handle_lost_peer(self, peer: Peer) -> None:
        """Handle a peer going out of range."""
        self.logger.info(f"Lost peer: {peer.full_name}")
        
        # Notify view if available
        if self.view and hasattr(self.view, 'on_lost_peer'):
            self.view.on_lost_peer(peer)
        
        # Notify plugins
        plugin_manager.on('peer_lost', self, peer)
    
    def get_peer_count(self) -> int:
        return len(self.peers)
    
    def get_closest_peer(self) -> Optional[Peer]:
        return self.closest_peer
    
    def get_peers_by_relationship(self, relationship: PeerRelationship) -> list[Peer]:
        return [peer for peer in self.peers.values() if peer.relationship == relationship]
    
    def cumulative_encounters(self) -> int:
        return sum(peer.encounters for peer in self.peers.values())


# Legacy class for backward compatibility
class AsyncAdvertiser(MeshAdvertiser):
    """Legacy class name for backward compatibility."""
    pass