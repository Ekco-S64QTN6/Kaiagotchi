import subprocess
import requests
import logging

# FIX 1: Correct the casing of the project import name
import kaiagotchi 

# pwngrid-peer is running on port 8666
API_ADDRESS = "http://127.0.0.1:8666/api/v1"

def is_connected():
    """Checks connectivity to the external opwngrid uptime API."""
    try:
        # Check an external host to ensure internet connectivity
        host = 'https://api.opwngrid.xyz/api/v1/uptime'
        # FIX 1: Use the correct, lowercase module name for version
        headers = {'user-agent': f'Kaiagotchi/{kaiagotchi.__version__}'} 
        r = requests.get(host, headers=headers, timeout=(30.0, 60.0))
        if r.json().get('isUp'):
            return True
    except Exception:
        # Catch all exceptions (connection error, timeout, JSON parsing error)
        pass
    return False

def call(path, obj=None):
    """
    Makes an API call to the local pwngrid-peer instance.

    Raises Exception on non-200 status codes.
    """
    url = '%s%s' % (API_ADDRESS, path)
    
    # Define common timeout settings
    timeout_settings = (30.0, 60.0) 

    if obj is None:
        r = requests.get(url, headers=None, timeout=timeout_settings)
    elif isinstance(obj, dict):
        r = requests.post(url, headers=None, json=obj, timeout=timeout_settings)
    else:
        # For non-dict data, send as raw body
        r = requests.post(url, headers=None, data=obj, timeout=timeout_settings)

    if r.status_code != 200:
        raise Exception(f"(status {r.status_code}) {r.text}")
    return r.json()

def advertise(enabled=True):
    """
    Enables or disables the peer-to-peer advertising/mesh functionality.
    
    FIX 2: Refactor ambiguous string formatting for clarity.
    """
    status = 'true' if enabled else 'false'
    return call(f"/mesh/{status}")

def update_data(last_session: 'SessionInfo', enabled: list, language: str):
    """
    Reports the agent's current state, session data, and system info to the grid.
    
    NOTE: Using subprocess.getoutput is generally discouraged in favor of 
    subprocess.run() for better error handling, but is left for now.
    """
    # FIX 1: Use the correct, lowercase module name for version
    data = {
        'session': {
            'duration': last_session.duration,
            'duration_human': last_session.duration_human,
            'start': last_session.start,
            'stop': last_session.stop,
            'epochs': last_session.epochs,
            'train_epochs': last_session.train_epochs,
            'avg_reward': last_session.avg_reward,
            'min_reward': last_session.min_reward,
            'max_reward': last_session.max_reward,
            'deauthed': last_session.deauthed,
            'associated': last_session.associated,
            'handshakes': last_session.handshakes,
            'peers': last_session.peers,
        },
        'uname': subprocess.getoutput("uname -a"),
        'version': kaiagotchi.__version__,
        'build': "Kaiagotchi by Jayofelony",
        'plugins': enabled,
        'language': language,
        'bettercap': subprocess.getoutput("bettercap -version"),
        'opwngrid': subprocess.getoutput("pwngrid -version")
    }

    logging.debug("updating grid data: %s" % data)

    call("/data", data)


def report_ap(essid, bssid):
    """Reports a newly discovered or interesting Access Point to the grid."""
    try:
        call("/report/ap", {
            'essid': essid,
            'bssid': bssid,
        })
        return True
    except Exception:
        # Use logging.exception to log the full traceback
        logging.exception(f"Error while reporting ap {essid}({bssid})")
        return False


def inbox(page=1, with_pager=False):
    """Fetches a list of messages from the agent's grid inbox."""
    obj = call("/inbox?p=%d" % page)
    return obj["messages"] if not with_pager else obj


def inbox_message(id):
    """Fetches a specific message from the grid inbox."""
    return call(f"/inbox/{id}")


def inbox_delete(id):
    """Deletes a message from the grid inbox."""
    return call(f"/inbox/delete/{id}")

def get_peers():
    """Retrieves the list of connected peers in the mesh network."""
    return call("/mesh/peers")

def block_bssid(bssid):
    """Blocks a BSSID from being reported or interacted with by peers."""
    return call(f"/mesh/block/{bssid}")

def unblock_bssid(bssid):
    """Unblocks a BSSID."""
    return call(f"/mesh/unblock/{bssid}")

def get_config():
    """Retrieves the current grid configuration."""
    return call("/config")

def update_config(key, value):
    """Updates a configuration key-value pair on the grid."""
    return call("/config", {key: value})
