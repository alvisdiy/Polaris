"""Repository for ExplorationRun rows (run tracking + metrics snapshot)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from database.models.exploration_run import ExplorationRun, ExplorationRunStatus


class RunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def fail_stale_running(self, country_id, reason: str = "run interrupted; finalized by a later run") -> int:
        """Close out RUNNING rows left behind by crashed or killed processes.

        A run whose process died never finalizes itself; leaving it RUNNING
        forever misreports engine state. Called at the start of a new run for
        the country — whatever is still RUNNING by then is by definition from
        a dead process, since one country is explored by one engine at a time.
        """
        stale = (
            self.session.query(ExplorationRun)
            .filter(
                ExplorationRun.country_id == country_id,
                ExplorationRun.status == ExplorationRunStatus.RUNNING,
            )
            .all()
        )
        for run in stale:
            run.status = ExplorationRunStatus.FAILED
            metrics = dict(run.metrics or {})
            metrics["fatal_error"] = metrics.get("fatal_error") or reason
            run.metrics = metrics
            run.finished_at = datetime.now(timezone.utc)
        if stale:
            self.session.commit()
        return len(stale)

    def start_run(self, country_id, config: dict[str, Any], bounds: dict[str, Any]) -> ExplorationRun:
        run = ExplorationRun(
            country_id=country_id,
            status=ExplorationRunStatus.RUNNING,
            config_snapshot=config,
            bounds_snapshot=bounds,
            metrics={},
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(run)
        self.session.flush()
        # Commit + refresh so the run row survives any mid-run rollback: the
        # loop commits periodically and rolls back on candidate errors, and a
        # run record that vanishes with them would orphan all artifacts of
        # the failed attempt.
        self.session.commit()
        self.session.refresh(run)
        return run

    def update_metrics(self, run: ExplorationRun, metrics: dict[str, Any]) -> None:
        run.metrics = metrics
        self.session.flush()

    def finish_run(self, run: ExplorationRun, status: str, metrics: dict[str, Any]) -> None:
        run.status = status
        run.metrics = metrics
        run.finished_at = datetime.now(timezone.utc)
        self.session.flush()

    def get_run(self, run_id: UUID) -> ExplorationRun | None:
        return self.session.query(ExplorationRun).filter(ExplorationRun.run_id == run_id).first()
