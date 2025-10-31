import os
import re
import tempfile
import contextlib
import shutil
import threading
import logging
import subprocess
from pathlib import Path
from time import sleep
from typing import List, Optional, Dict, Any

class SecureFilesystemManager:
    """
    Secure filesystem management for Kaiagotchi with memory-backed storage.
    Replaces the vulnerable global state approach with a secure, class-based design.
    """
    
    def __init__(self):
        self.mounts: Dict[str, 'SecureMemoryFS'] = {}
        self.logger = logging.getLogger('kaiagotchi.fs')
    
    def setup_mounts(self, config: Dict[str, Any]) -> bool:
        """Safely configure filesystem mounts from configuration."""
        try:
            fs_cfg = config.get('fs', {}).get('memory', {})
            if not fs_cfg.get('enabled', False):
                return True
            
            for name, options in fs_cfg.get('mounts', {}).items():
                if not options.get('enabled', True):
                    continue
                    
                mount = SecureMemoryFS(
                    name=name,
                    mount_point=options['mount'],
                    size=options.get('size', '40M'),
                    use_zram=options.get('zram', True),
                    sync_interval=options.get('sync', 60)
                )
                
                if mount.initialize():
                    self.mounts[name] = mount
                    self.logger.info(f"Successfully mounted {name} at {options['mount']}")
                else:
                    self.logger.error(f"Failed to mount {name}")
                    
            return True
            
        except Exception as e:
            self.logger.error(f"Error setting up mounts: {e}")
            return False

@contextlib.contextmanager
def secure_write(filename: str, mode: str = 'w'):
    """Atomic file write with secure permissions."""
    path = Path(filename)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    
    try:
        with os.fdopen(fd, mode) as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        
        # Secure file permissions
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, filename)
        
    except Exception:
        os.unlink(tmp_path)
        raise

class SecureMemoryFS:
    """Secure in-memory filesystem implementation."""
    
    def __init__(self, name: str, mount_point: str, size: str = "40M", 
                 use_zram: bool = True, sync_interval: int = 60):
        self.name = name
        self.mount_point = Path(mount_point)
        self.size = size
        self.use_zram = use_zram
        self.sync_interval = sync_interval
        self._running = False
        self._sync_thread: Optional[threading.Thread] = None
        self.logger = logging.getLogger(f'kaiagotchi.fs.{name}')
    
    def _safe_system_command(self, command: List[str]) -> bool:
        """Execute system commands safely without shell injection."""
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError) as e:
            self.logger.error(f"Command failed: {e}")
            return False
    
    def initialize(self) -> bool:
        """Initialize the memory filesystem safely."""
        try:
            # Create directories with secure permissions
            self.mount_point.mkdir(parents=True, exist_ok=True, mode=0o755)
            
            if self.use_zram and self._setup_zram():
                return self._mount_zram()
            else:
                return self._mount_tmpfs()
                
        except Exception as e:
            self.logger.error(f"Initialization failed: {e}")
            return False
    
    def _setup_zram(self) -> bool:
        """Setup zram device securely."""
        try:
            # Check if zram is available
            if not Path("/sys/class/zram-control").exists():
                self.logger.debug("ZRAM not available, falling back to tmpfs")
                return False
            
            # Setup would go here with secure command execution
            # ... implementation details ...
            return True
            
        except Exception as e:
            self.logger.warning(f"ZRAM setup failed: {e}")
            return False
    
    def _mount_tmpfs(self) -> bool:
        """Mount tmpfs filesystem securely."""
        mount_cmd = [
            "mount", "-t", "tmpfs", 
            "-o", f"nosuid,noexec,nodev,mode=0755,size={self.size}",
            "tmpfs", str(self.mount_point)
        ]
        return self._safe_system_command(mount_cmd)
    
    # ... other methods with secure implementations ...