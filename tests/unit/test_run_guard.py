"""Guards that keep a live exploration away from the development database."""

from __future__ import annotations

import pytest

from services.exploration.run_guard import (
    NonScratchDatabase,
    assert_scratch_database,
    database_name,
    is_local_host,
    is_scratch_database,
)

LOCAL_SCRATCH = "postgresql+psycopg://postgres:secret@localhost:5432/polaris_scratch"
LOCAL_TEST = "postgresql+psycopg://postgres:secret@127.0.0.1:5432/polaris_test"
LOCAL_DEV = "postgresql+psycopg://postgres:secret@localhost:5432/polaris"
REMOTE_SCRATCH = "postgresql+psycopg://postgres:secret@db.example.com:5432/polaris_scratch"


class TestDatabaseName:
    def test_reads_the_path_component(self):
        assert database_name(LOCAL_SCRATCH) == "polaris_scratch"

    def test_ignores_query_string(self):
        assert database_name(LOCAL_DEV + "?sslmode=disable") == "polaris"

    def test_unix_socket_url_is_local(self):
        url = "postgresql+psycopg://postgres@/polaris_scratch?host=/var/run/postgresql"
        assert database_name(url) == "polaris_scratch"
        assert is_local_host(url)
        assert is_scratch_database(url)


class TestScratchClassification:
    def test_local_scratch_and_test_suffixes_are_disposable(self):
        assert is_scratch_database(LOCAL_SCRATCH)
        assert is_scratch_database(LOCAL_TEST)

    def test_local_development_database_is_not(self):
        assert not is_scratch_database(LOCAL_DEV)

    def test_remote_database_is_never_disposable(self):
        """A remote host named *scratch is still a remote database."""
        assert not is_scratch_database(REMOTE_SCRATCH)
        assert not is_local_host(REMOTE_SCRATCH)


class TestAssertScratch:
    def test_allows_a_scratch_database(self):
        assert_scratch_database(LOCAL_SCRATCH)  # must not raise

    def test_refuses_the_development_database(self):
        with pytest.raises(NonScratchDatabase) as excinfo:
            assert_scratch_database(LOCAL_DEV)
        message = str(excinfo.value)
        assert "polaris" in message
        assert "_scratch" in message

    def test_explicit_override(self):
        assert_scratch_database(LOCAL_DEV, allow_non_scratch=True)

    def test_environment_override(self, monkeypatch):
        monkeypatch.setenv("POLARIS_ALLOW_NON_SCRATCH", "1")
        assert_scratch_database(LOCAL_DEV)

    def test_other_environment_values_do_not_override(self, monkeypatch):
        monkeypatch.setenv("POLARIS_ALLOW_NON_SCRATCH", "true")
        with pytest.raises(NonScratchDatabase):
            assert_scratch_database(LOCAL_DEV)
