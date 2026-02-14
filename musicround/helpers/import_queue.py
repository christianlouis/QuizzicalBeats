"""Import queue and worker implementation for asynchronous playlist imports."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from queue import PriorityQueue, Empty
from typing import Optional
from flask import current_app
from flask_login import login_user, logout_user

from musicround.models import User, db
from musicround.helpers.import_helper import ImportHelper


@dataclass(order=True)
class ImportJob:
    """Represents a single import job."""

    priority: int
    service_name: str = field(compare=False)
    item_type: str = field(compare=False)
    item_id: str = field(compare=False)
    user_id: int = field(compare=False)


class ImportQueue:
    """Priority queue for import jobs."""

    def __init__(self) -> None:
        self._queue: PriorityQueue[tuple[int, int, ImportJob]] = PriorityQueue()
        self._counter = 0
        self._lock = threading.Lock()

    def add_job(self, job: ImportJob) -> None:
        """Add a job to the queue."""
        with self._lock:
            self._counter += 1
            self._queue.put((job.priority, self._counter, job))

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


class ImportWorker(threading.Thread):
    """Background worker thread for processing import jobs."""

    def __init__(self, app, queue: ImportQueue) -> None:
        super().__init__(daemon=True)
        self.app = app
        self.queue = queue
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """Stop the worker loop."""
        self._stop_event.set()

    def run(self) -> None:
        with self.app.app_context():
            while not self._stop_event.is_set():
                job = self.queue.get_job(timeout=1.0)
                if job is None:
                    continue
                self._process_job(job)
                self.queue.task_done()

    def _process_job(self, job: ImportJob) -> None:
        user = User.query.get(job.user_id)
        if not user:
            current_app.logger.error("Import job for unknown user %s", job.user_id)
            return
        with self.app.test_request_context():
            login_user(user)
            try:
                current_app.logger.info(
                    "Processing import job: service=%s type=%s id=%s user=%s priority=%s",
                    job.service_name,
                    job.item_type,
                    job.item_id,
                    job.user_id,
                    job.priority,
                )
                ImportHelper.import_item(job.service_name, job.item_type, job.item_id)
                db.session.commit()
            except Exception as exc:  # pylint: disable=broad-except
                current_app.logger.error("Import job failed: %s", exc, exc_info=True)
                db.session.rollback()
            finally:
                logout_user()
