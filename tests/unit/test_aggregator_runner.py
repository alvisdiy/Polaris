import pytest

from scripts.run_aggregator_discovery import isolated_database_url


def test_persistence_runner_requires_explicit_database(monkeypatch):
    monkeypatch.delenv("POLARIS_AGGREGATOR_TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/polaris")

    with pytest.raises(RuntimeError, match="POLARIS_AGGREGATOR_TEST_DATABASE_URL"):
        isolated_database_url()


@pytest.mark.parametrize(
    "value, message",
    [
        ("sqlite:///polaris_test.db", "requires PostgreSQL"),
        ("postgresql://localhost/polaris", "must end with _test or _scratch"),
        ("postgresql://example.org/polaris_scratch", "non-local database host"),
    ],
)
def test_persistence_runner_rejects_unsafe_database_targets(monkeypatch, value, message):
    monkeypatch.setenv("POLARIS_AGGREGATOR_TEST_DATABASE_URL", value)

    with pytest.raises(RuntimeError, match=message):
        isolated_database_url()


def test_persistence_runner_accepts_named_local_scratch_database(monkeypatch):
    monkeypatch.setenv(
        "POLARIS_AGGREGATOR_TEST_DATABASE_URL",
        "postgresql+psycopg://postgres:secret@localhost:5432/polaris_scratch",
    )

    url = isolated_database_url()

    assert url.database == "polaris_scratch"
