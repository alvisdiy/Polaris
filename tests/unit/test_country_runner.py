"""The country runner's plan-only mode and its database guard.

Plan-only is the mode an operator uses to see what a run would ask for. It must
not need a database or a network, otherwise "just look at the plan" is a live
operation with extra steps.
"""

from __future__ import annotations

import builtins

import pytest

from scripts.run_country_exploration import build_plan, print_plan


class TestBuildPlan:
    def test_builds_a_bounded_plan_from_country_config(self):
        config, plan = build_plan("JP")

        assert config.iso2 == "JP"
        assert plan, "a configured country must produce queries"
        assert len(plan) <= config.max_queries_per_run
        assert all(item.text.strip() for item in plan)
        # Deterministic: the same country produces the same plan.
        _, again = build_plan("JP")
        assert [item.text for item in plan] == [item.text for item in again]

    def test_plan_does_not_open_a_database(self, monkeypatch):
        """build_plan imports nothing from database.*; make that observable."""
        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name.startswith("database"):
                raise AssertionError(f"plan-only imported {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", guarded_import)
        config, plan = build_plan("JP")

        assert config.iso2 == "JP"
        assert plan


class TestPrintPlan:
    def test_prints_queries_and_declares_no_database(self, capsys):
        config, plan = build_plan("JP")

        print_plan(config, plan)

        out = capsys.readouterr().out
        assert "COUNTRY EXPLORATION PLAN — JP" in out
        assert "Database:      not opened" in out
        assert f"Queries ({len(plan)})" in out
        assert plan[0].text in out

    def test_unknown_country_is_an_error(self):
        with pytest.raises(FileNotFoundError):
            build_plan("ZZ")
