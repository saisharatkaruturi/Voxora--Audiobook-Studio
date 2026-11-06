"""OCR_PROVIDER=none (small servers): scans are refused with a clear message, nothing loads."""

import pytest

from app.core.errors import ProviderUnavailableError
from app.providers.ocr import get_ocr_provider


def test_ocr_can_be_switched_off():
    with pytest.raises(ProviderUnavailableError) as err:
        get_ocr_provider("none")
    assert "selectable text" in err.value.message


def test_plain_postgres_links_are_accepted(monkeypatch):
    """Supabase prints postgresql://...; the app should not need it rewritten by hand."""
    from app.core import config

    for given in ("postgresql://u:p@host:5432/postgres", "postgres://u:p@host:5432/postgres"):
        monkeypatch.setenv("DATABASE_URL", given)
        config.get_settings.cache_clear()
        try:
            assert config.get_settings().database_url == "postgresql+psycopg://u:p@host:5432/postgres"
        finally:
            monkeypatch.undo()
            config.get_settings.cache_clear()
