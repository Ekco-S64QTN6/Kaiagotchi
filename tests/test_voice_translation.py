import kaiagotchi.ui.voice.voice as voice_module
from kaiagotchi.ui.voice import Voice


def test_voice_uses_gettext_translation_callable(monkeypatch):
    class FakeTranslation:
        def gettext(self, message: str) -> str:
            return f"translated:{message}"

    monkeypatch.setattr(
        voice_module.gettext,
        "translation",
        lambda *_args, **_kwargs: FakeTranslation(),
    )

    voice = Voice(lang="fr")

    assert voice.custom("Signal acquired.") == "translated:Signal acquired."
    assert voice.default() == (
        "translated:Awaiting transmission. Static is preferable to silence."
    )


def test_voice_falls_back_to_identity_translation(monkeypatch):
    def fail_translation(*_args, **_kwargs):
        raise OSError("translation catalogue unavailable")

    monkeypatch.setattr(voice_module.gettext, "translation", fail_translation)

    voice = Voice(lang="missing")

    assert voice.custom("untranslated message") == "untranslated message"
    assert voice.default() == "Awaiting transmission. Static is preferable to silence."
