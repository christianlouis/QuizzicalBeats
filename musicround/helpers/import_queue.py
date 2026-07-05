"""Import queue and worker implementation for asynchronous playlist imports."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from queue import PriorityQueue, Empty
from typing import Any, Optional
from flask import current_app
from flask_login import login_user, logout_user
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from musicround.models import ImportJobRecord, User, db
from musicround.helpers.import_helper import ImportHelper
from musicround.helpers.spotify_helper import get_spotify_token


@dataclass(order=True)
class ImportJob:
    """Represents a single import job."""

    priority: int
    service_name: str = field(compare=False)
    item_type: str = field(compare=False)
    item_id: str = field(compare=False)
    user_id: int = field(compare=False)
    spotify_token: Optional[str] = field(default=None, compare=False)
    record_id: Optional[int] = field(default=None, compare=False)


class ImportQueue:
    """Priority queue for import jobs with database-backed job records."""

    def __init__(self) -> None:
        self._queue: PriorityQueue[tuple[int, int, ImportJob]] = PriorityQueue()
        self._counter = 0
        self._lock = threading.Lock()

    @staticmethod
    def normalize_priority(priority: Any, default: int = 10) -> int:
        """Return a bounded integer priority. Lower numbers run first."""
        try:
            normalized = int(priority)
        except (TypeError, ValueError):
            normalized = default
        return max(0, min(100, normalized))

    def add_job(self, job: ImportJob) -> None:
        """Add a job to the in-memory work queue."""
        job.priority = self.normalize_priority(job.priority)
        with self._lock:
            self._counter += 1
            self._queue.put((job.priority, self._counter, job))

    def enqueue(
        self,
        service_name: str,
        item_type: str,
        item_id: str,
        user_id: int,
        priority: Any = 10,
        spotify_token: Optional[str] = None,
    ) -> ImportJobRecord:
        """Create a persistent job record and enqueue it for local workers."""
        normalized_priority = self.normalize_priority(priority)
        record = ImportJobRecord(
            service_name=service_name,
            item_type=item_type,
            item_id=item_id,
            user_id=user_id,
            priority=normalized_priority,
            status="pending",
        )
        db.session.add(record)
        db.session.commit()
        self.enqueue_record(record, spotify_token=spotify_token)
        return record

    def enqueue_record(self, record: ImportJobRecord, spotify_token: Optional[str] = None) -> None:
        """Enqueue an existing pending job record."""
        self.add_job(
            ImportJob(
                priority=record.priority,
                service_name=record.service_name,
                item_type=record.item_type,
                item_id=record.item_id,
                user_id=record.user_id,
                spotify_token=spotify_token,
                record_id=record.id,
            )
        )

    def mark_abandoned_processing_records(self) -> int:
        """Fail jobs left processing by an earlier process restart."""
        records = ImportJobRecord.query.filter_by(status="processing").all()
        for record in records:
            record.status = "failed"
            record.completed_at = datetime.utcnow()
            record.error_message = (
                "Import worker restarted while this job was processing. "
                "Queue the import again if it still needs to run."
            )
        if records:
            db.session.commit()
        return len(records)

    def enqueue_pending_records(self) -> int:
        """Load pending database jobs into the local priority queue."""
        records = (
            ImportJobRecord.query.filter_by(status="pending")
            .order_by(
                ImportJobRecord.priority.asc(),
                ImportJobRecord.created_at.asc(),
                ImportJobRecord.id.asc(),
            )
            .all()
        )
        for record in records:
            self.enqueue_record(record)
        return len(records)

    def get_job(self, timeout: Optional[float] = None) -> Optional[ImportJob]:
        """Retrieve the next job from the queue."""
        try:
            _, _, job = self._queue.get(timeout=timeout)
            return job
        except Empty:
            return None

    def task_done(self) -> None:
        """Signal that a previously fetched job is complete."""
        self._queue.task_done()

    def qsize(self) -> int:
        """Return the number of jobs waiting in the local queue."""
        return self._queue.qsize()

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a thread-safe snapshot of queued jobs for status pages."""
        with self._lock:
            queue_items = list(self._queue.queue)

        return [
            {
                "priority": priority,
                "counter": counter,
                "service": job.service_name,
                "type": job.item_type,
                "item_id": job.item_id,
                "user_id": job.user_id,
                "record_id": job.record_id,
            }
            for priority, counter, job in sorted(queue_items)
        ]


class ImportWorker(threading.Thread):
    """Background worker thread for processing import jobs."""

    _claim_lock = threading.Lock()

    def __init__(self, app, queue: ImportQueue, worker_id: Optional[str] = None) -> None:
        super().__init__(daemon=True)
        self.app = app
        self.queue = queue
        self.worker_id = worker_id or self.name
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """Stop the worker loop."""
        self._stop_event.set()

    def run(self) -> None:
        with self.app.app_context():
            while not self._stop_event.is_set():
                job = self.queue.get_job(timeout=1.0)
                from_local_queue = job is not None
                if job is None:
                    job = self._get_next_pending_job()
                if job is None:
                    continue
                try:
                    self._process_job(job)
                finally:
                    if from_local_queue:
                        self.queue.task_done()

    def _get_next_pending_job(self) -> Optional[ImportJob]:
        try:
            record = (
                ImportJobRecord.query.filter_by(status="pending")
                .order_by(
                    ImportJobRecord.priority.asc(),
                    ImportJobRecord.created_at.asc(),
                    ImportJobRecord.id.asc(),
                )
                .first()
            )
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.warning("Could not poll import job table: %s", exc)
            return None

        if not record:
            return None
        return ImportJob(
            priority=record.priority,
            service_name=record.service_name,
            item_type=record.item_type,
            item_id=record.item_id,
            user_id=record.user_id,
            record_id=record.id,
        )

    def _process_job(self, job: ImportJob) -> None:
        with self.app.test_request_context():
            record = None
            logged_in = False
            try:
                record = self._claim_record(job)
                if job.record_id and record is None:
                    return

                user = User.query.get(job.user_id)
                if not user:
                    current_app.logger.error("Import job for unknown user %s", job.user_id)
                    self._mark_failed(record, f"Unknown user id {job.user_id}")
                    return

                login_user(user)
                logged_in = True
                current_app.logger.info(
                    "Processing import job: record=%s service=%s type=%s id=%s user=%s priority=%s",
                    job.record_id,
                    job.service_name,
                    job.item_type,
                    job.item_id,
                    job.user_id,
                    job.priority,
                )
                import_kwargs = {}
                if job.service_name.lower() == 'spotify':
                    access_token = job.spotify_token
                    if not access_token:
                        access_token, _token_source = get_spotify_token()
                    import_kwargs['spotify_token'] = access_token

                result = ImportHelper.import_item(
                    job.service_name,
                    job.item_type,
                    job.item_id,
                    **import_kwargs,
                )
                imported_count, skipped_count, error_message = self._summarize_result(result)
                self._mark_completed(record, imported_count, skipped_count, error_message)
                db.session.commit()
            except Exception as exc:  # pylint: disable=broad-except
                current_app.logger.error("Import job failed: %s", exc, exc_info=True)
                db.session.rollback()
                self._mark_failed(record, str(exc))
            finally:
                if logged_in:
                    logout_user()
                db.session.remove()

    def _claim_record(self, job: ImportJob) -> Optional[ImportJobRecord]:
        if job.record_id is None:
            return None

        with self._claim_lock:
            try:
                statement = (
                    update(ImportJobRecord)
                    .where(
                        ImportJobRecord.id == job.record_id,
                        ImportJobRecord.status == "pending",
                    )
                    .values(status="processing", started_at=datetime.utcnow())
                )
                result = db.session.execute(statement)
                if result.rowcount != 1:
                    db.session.rollback()
                    return None
                db.session.commit()
            except SQLAlchemyError as exc:
                db.session.rollback()
                current_app.logger.warning(
                    "Could not claim import job record %s: %s",
                    job.record_id,
                    exc,
                )
                return None

        return ImportJobRecord.query.get(job.record_id)

    def _mark_completed(
        self,
        record: Optional[ImportJobRecord],
        imported_count: int,
        skipped_count: int,
        error_message: Optional[str],
    ) -> None:
        if not record:
            return
        record.status = "completed"
        record.completed_at = datetime.utcnow()
        record.imported_count = imported_count
        record.skipped_count = skipped_count
        record.error_message = error_message

    def _mark_failed(self, record: Optional[ImportJobRecord], error_message: str) -> None:
        if not record:
            return
        record.status = "failed"
        record.completed_at = datetime.utcnow()
        record.error_message = error_message
        db.session.add(record)
        db.session.commit()

    @staticmethod
    def _summarize_result(result: Any) -> tuple[int, int, Optional[str]]:
        if isinstance(result, dict):
            errors = result.get("errors") or []
            if isinstance(errors, str):
                errors = [errors]
            skipped_count = result.get("skipped_count")
            if skipped_count is None:
                skipped_count = sum(
                    int(result.get(key, 0) or 0)
                    for key in (
                        "skipped_existing_count",
                        "skipped_no_preview_count",
                        "skipped_no_match_count",
                    )
                )
            return (
                int(result.get("imported_count", 0) or 0),
                int(skipped_count or 0),
                "\n".join(str(error) for error in errors) or None,
            )

        if isinstance(result, list):
            return (len(result), 0, None)

        return (0, 0, None)


def enqueue_import_job(
    queue: ImportQueue,
    service_name: str,
    item_type: str,
    item_id: str,
    user_id: int,
    priority: Any = 10,
    spotify_token: Optional[str] = None,
) -> ImportJobRecord:
    """Create and enqueue an import job using the app-wide queue."""
    return queue.enqueue(
        service_name,
        item_type,
        item_id,
        user_id,
        priority,
        spotify_token=spotify_token,
    )
