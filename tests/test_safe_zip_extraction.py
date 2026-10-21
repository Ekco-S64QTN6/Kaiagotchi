import stat
import zipfile

from kaiagotchi.core.utils import unzip


def test_unzip_honors_strip_dirs(tmp_path):
    archive = tmp_path / "safe.zip"
    destination = tmp_path / "out"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("package/docs/readme.txt", "safe")

    assert unzip(str(archive), str(destination), strip_dirs=1)
    assert (destination / "docs" / "readme.txt").read_text(encoding="utf-8") == "safe"
    assert not (destination / "package").exists()


def test_unzip_rejects_parent_traversal_before_writing(tmp_path):
    archive = tmp_path / "malicious.zip"
    destination = tmp_path / "out"
    outside = tmp_path / "escape.txt"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("safe.txt", "would be written if extraction started")
        zf.writestr("../escape.txt", "escaped")

    assert not unzip(str(archive), str(destination))
    assert not (destination / "safe.txt").exists()
    assert not outside.exists()


def test_unzip_rejects_windows_absolute_and_traversal_paths(tmp_path):
    archive = tmp_path / "windows.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("C:\\Windows\\outside.txt", "bad")
    assert not unzip(str(archive), str(tmp_path / "out"))


def test_unzip_rejects_symlink_entries(tmp_path):
    archive = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("outside-link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(info, "../../escape.txt")
    assert not unzip(str(archive), str(tmp_path / "out"))
