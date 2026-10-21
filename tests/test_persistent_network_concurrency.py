import threading

from kaiagotchi.storage.persistent_network import PersistentNetwork


def test_network_state_writes_are_serialized_with_filesystem_sync(tmp_path):
    network = PersistentNetwork(storage_dir=str(tmp_path))
    network._sync_thread.join(timeout=5.0)
    assert not network._sync_thread.is_alive()

    lock = network._state_lock
    started = threading.Event()
    completed = threading.Event()

    def update_state():
        started.set()
        network.update_bssid(
            bssid="00:11:22:33:44:55",
            essid="Test-AP",
            packets=1,
            channel="6",
            encryption="WPA2",
        )
        completed.set()

    lock.acquire()
    worker = threading.Thread(target=update_state)
    worker.start()
    try:
        assert started.wait(timeout=1.0)
        # The decorated state write must wait until an in-flight state operation
        # releases the same reentrant lock used by startup reconciliation.
        assert not completed.wait(timeout=0.05)
    finally:
        lock.release()

    assert completed.wait(timeout=2.0)
    worker.join(timeout=2.0)
    assert not worker.is_alive()
    assert "00:11:22:33:44:55" in network.get_all_bssids()
