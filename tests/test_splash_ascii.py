from types import SimpleNamespace

import kaiagotchi.ui.splash as splash_module
from kaiagotchi.ui.splash import SplashScreen


def test_load_image_as_ascii_converts_grayscale_pixels_to_fixed_width_rows(
    tmp_path, monkeypatch
):
    image_path = tmp_path / "kaia.png"
    image_path.write_bytes(b"synthetic image placeholder")

    class FakeImage:
        size = (4, 4)

        def resize(self, size, resample):
            assert size == (4, 2)
            assert resample == "lanczos"
            return self

        def convert(self, mode):
            assert mode == "L"
            return self

        def getdata(self):
            return [0, 25, 50, 75, 100, 125, 150, 175]

    fake_image = FakeImage()
    fake_pillow = SimpleNamespace(
        open=lambda _path: fake_image,
        Resampling=SimpleNamespace(LANCZOS="lanczos"),
    )
    monkeypatch.setattr(splash_module, "Image", fake_pillow)

    splash = SplashScreen.__new__(SplashScreen)
    splash.image_path = image_path

    assert splash._load_image_as_ascii(width=4) == "@#S%\n?*+;"
