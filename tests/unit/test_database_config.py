import pytest

from database.config import get_database_url

pytestmark = pytest.mark.unit


def test_test_mode_requires_explicit_isolated_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/polaris")
    monkeypatch.delenv("POLARIS_TEST_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="POLARIS_TEST_DATABASE_URL"):
        get_database_url()


@pytest.mark.parametrize(
    "value, message",
    [
        ("sqlite:///polaris_test.db", "PostgreSQL"),
        ("postgresql://localhost/polaris", "_test or _scratch"),
        ("postgresql://example.org/polaris_scratch", "non-local test database host"),
    ],
)
def test_test_mode_rejects_unsafe_database_targets(monkeypatch, value, message):
    monkeypatch.setenv("POLARIS_TEST_DATABASE_URL", value)

    with pytest.raises(RuntimeError, match=message):
        get_database_url()


def test_test_mode_accepts_explicit_local_scratch_database(monkeypatch):
    value = "postgresql+psycopg://postgres:secret@localhost:5432/polaris_test"
    monkeypatch.setenv("POLARIS_TEST_DATABASE_URL", value)

    assert get_database_url() == value


def test_test_mode_ignores_database_url_without_explicit_target(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/polaris")
    monkeypatch.delenv("POLARIS_TEST_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="POLARIS_TEST_DATABASE_URL"):
        get_database_url()


def test_test_mode_uses_explicit_test_url_over_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/polaris")
    monkeypatch.setenv(
        "POLARIS_TEST_DATABASE_URL", "postgresql://localhost/polaris_scratch"
    )

    assert get_database_url() == "postgresql://localhost/polaris_scratch"
