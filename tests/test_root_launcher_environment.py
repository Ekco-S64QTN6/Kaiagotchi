from pathlib import Path
import subprocess


def test_root_launcher_does_not_preserve_callers_path_or_environment():
    root = Path(__file__).resolve().parents[1]
    script = root / "run_kaiagotchi.sh"
    content = script.read_text(encoding="utf-8")

    assert subprocess.run(
        ["bash", "-n", str(script)],
        check=False,
        capture_output=True,
        text=True,
    ).returncode == 0
    assert 'sudo -E' not in content
    assert 'PATH=$PATH' not in content
    assert 'KAIAGOTCHI_INTERFACE=$KAIAGOTCHI_INTERFACE' in content
    assert 'KAIA_CONFIG=$KAIA_CONFIG' in content
