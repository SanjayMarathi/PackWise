import pytest

AI_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


@pytest.fixture(autouse=True)
def no_ai_keys(monkeypatch):
    """Tests decide the provider explicitly; a developer's real keys must never leak in."""
    for key in AI_KEYS:
        monkeypatch.delenv(key, raising=False)
