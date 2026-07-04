"""Tests for the import queue data structures."""
import pytest
import threading
import time
from datetime import datetime
from unittest.mock import patch

from musicround.helpers.import_queue import (
    ImportJob,
    ImportQueue,
    ImportWorker,
    enqueue_import_job,
)
from musicround.models import ImportJobRecord, User, db


class TestImportJob:
    """Tests for the ImportJob dataclass."""

    def test_import_job_creation(self):
        """Test creating an ImportJob with all fields."""
        job = ImportJob(
            priority=5,
            service_name='spotify',
            item_type='playlist',
            item_id='abc123',
            user_id=1,
        )
        assert job.priority == 5
        assert job.service_name == 'spotify'
        assert job.item_type == 'playlist'
        assert job.item_id == 'abc123'
        assert job.user_id == 1

    def test_import_job_ordering_by_priority(self):
        """Test that ImportJobs are ordered by priority (lower = higher priority)."""
        job_high = ImportJob(priority=1, service_name='spotify', item_type='track',
                             item_id='a', user_id=1)
        job_low = ImportJob(priority=10, service_name='spotify', item_type='track',
                            item_id='b', user_id=1)
        assert job_high < job_low

    def test_import_job_equality(self):
        """Test that ImportJobs with the same priority compare as equal."""
        job1 = ImportJob(priority=5, service_name='spotify', item_type='track',
                         item_id='x', user_id=1)
        job2 = ImportJob(priority=5, service_name='deezer', item_type='album',
                         item_id='y', user_id=2)
        # Only priority is used for comparison
        assert job1 == job2

    def test_import_job_deezer(self):
        """Test creating a Deezer ImportJob."""
        job = ImportJob(
            priority=3,
            service_name='deezer',
            item_type='album',
            item_id='456',
            user_id=7,
        )
        assert job.service_name == 'deezer'
        assert job.item_type == 'album'


class TestImportQueue:
    """Tests for the ImportQueue class."""

    def test_queue_creation(self):
        """Test creating an ImportQueue."""
        queue = ImportQueue()
        assert queue is not None
        assert queue._counter == 0

    def test_add_and_get_job(self):
        """Test adding a job to the queue and retrieving it."""
        queue = ImportQueue()
        job = ImportJob(priority=5, service_name='spotify', item_type='track',
                        item_id='track1', user_id=1)
        queue.add_job(job)
        retrieved = queue.get_job(timeout=1.0)
        assert retrieved is not None
        assert retrieved.item_id == 'track1'

    def test_get_job_respects_priority(self):
        """Test that higher-priority jobs (lower number) are retrieved first."""
        queue = ImportQueue()
        low = ImportJob(priority=10, service_name='s', item_type='t', item_id='low', user_id=1)
        high = ImportJob(priority=1, service_name='s', item_type='t', item_id='high', user_id=1)
        low_again = ImportJob(priority=10, service_name='s', item_type='t', item_id='low2', user_id=1)
        queue.add_job(low)
        queue.add_job(high)
        queue.add_job(low_again)

        first = queue.get_job(timeout=0.1)
        assert first.item_id == 'high'

    def test_get_job_empty_returns_none(self):
        """Test that get_job returns None when the queue is empty."""
        queue = ImportQueue()
        result = queue.get_job(timeout=0.05)
        assert result is None

    def test_task_done(self):
        """Test that task_done can be called after retrieving a job."""
        queue = ImportQueue()
        job = ImportJob(priority=5, service_name='s', item_type='t', item_id='1', user_id=1)
        queue.add_job(job)
        queue.get_job(timeout=0.1)
        # Should not raise
        queue.task_done()

    def test_counter_increments(self):
        """Test that internal counter increments with each job added."""
        queue = ImportQueue()
        assert queue._counter == 0
        queue.add_job(ImportJob(priority=1, service_name='s', item_type='t', item_id='1', user_id=1))
        assert queue._counter == 1
        queue.add_job(ImportJob(priority=1, service_name='s', item_type='t', item_id='2', user_id=1))
        assert queue._counter == 2

    def test_fifo_within_same_priority(self):
        """Test that jobs with the same priority are retrieved in insertion order (FIFO)."""
        queue = ImportQueue()
        first = ImportJob(priority=5, service_name='s', item_type='t', item_id='first', user_id=1)
        second = ImportJob(priority=5, service_name='s', item_type='t', item_id='second', user_id=1)
        queue.add_job(first)
        queue.add_job(second)
        assert queue.get_job(timeout=0.1).item_id == 'first'
        assert queue.get_job(timeout=0.1).item_id == 'second'

    def test_thread_safety(self):
        """Test that the queue handles concurrent access safely."""
        queue = ImportQueue()
        results = []
        errors = []

        def producer():
            try:
                for i in range(5):
                    queue.add_job(ImportJob(
                        priority=i, service_name='s', item_type='t',
                        item_id=str(i), user_id=1,
                    ))
            except Exception as e:
                errors.append(e)

        def consumer():
            try:
                for _ in range(5):
                    job = queue.get_job(timeout=1.0)
                    if job:
                        results.append(job.item_id)
                        queue.task_done()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=producer)
        t2 = threading.Thread(target=consumer)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not errors
        assert len(results) == 5

    def test_enqueue_creates_record_and_queue_snapshot(self, app):
        """Test enqueue persists a pending job and exposes it in queue status data."""
        with app.app_context():
            user = User(username='queueuser', email='queue@example.com')
            user.password = 'QueuePass123!'
            db.session.add(user)
            db.session.commit()

            queue = ImportQueue()
            record = enqueue_import_job(
                queue=queue,
                service_name='spotify',
                item_type='playlist',
                item_id='playlist123',
                user_id=user.id,
                priority='4',
            )

            assert record.id is not None
            assert record.status == 'pending'
            assert record.priority == 4
            assert queue.qsize() == 1
            snapshot = queue.snapshot()
            assert snapshot[0]['record_id'] == record.id
            assert snapshot[0]['item_id'] == 'playlist123'

    def test_enqueue_pending_records_loads_database_jobs(self, app):
        """Test startup can reload pending jobs from the database."""
        with app.app_context():
            user = User(username='pendinguser', email='pending@example.com')
            user.password = 'QueuePass123!'
            db.session.add(user)
            db.session.flush()
            record = ImportJobRecord(
                service_name='deezer',
                item_type='album',
                item_id='album123',
                user_id=user.id,
                priority=2,
                status='pending',
            )
            db.session.add(record)
            db.session.commit()

            queue = ImportQueue()
            assert queue.enqueue_pending_records() == 1
            job = queue.get_job(timeout=0.1)
            assert job.record_id == record.id
            assert job.item_id == 'album123'

    def test_mark_abandoned_processing_records_fails_stale_jobs(self, app):
        """Test processing jobs left behind by a restart get a visible failure."""
        with app.app_context():
            user = User(username='staleuser', email='stale@example.com')
            user.password = 'QueuePass123!'
            db.session.add(user)
            db.session.flush()
            record = ImportJobRecord(
                service_name='spotify',
                item_type='playlist',
                item_id='stale',
                user_id=user.id,
                status='processing',
                started_at=datetime(2026, 1, 1, 12, 0, 0),
            )
            db.session.add(record)
            db.session.commit()

            queue = ImportQueue()
            assert queue.mark_abandoned_processing_records() == 1
            updated = ImportJobRecord.query.get(record.id)
            assert updated.status == 'failed'
            assert 'restarted' in updated.error_message


class TestImportWorker:
    """Tests for ImportWorker job processing."""

    def test_process_job_imports_as_user(self, app):
        """Test that _process_job logs in the target user and imports the item."""
        with app.app_context():
            user = User(username='workeruser', email='worker@example.com')
            user.password = 'WorkerPass123!'
            db.session.add(user)
            db.session.commit()

            worker = ImportWorker(app, ImportQueue())
            job = ImportJob(
                priority=1,
                service_name='deezer',
                item_type='track',
                item_id='123',
                user_id=user.id,
            )

            with patch('musicround.helpers.import_queue.ImportHelper.import_item') as mock_import:
                worker._process_job(job)

            mock_import.assert_called_once_with('deezer', 'track', '123')

    def test_process_job_updates_record_status(self, app):
        """Test that worker writes processing and completed state to ImportJobRecord."""
        with app.app_context():
            user = User(username='recordworker', email='recordworker@example.com')
            user.password = 'WorkerPass123!'
            db.session.add(user)
            db.session.commit()

            queue = ImportQueue()
            record = enqueue_import_job(
                queue=queue,
                service_name='deezer',
                item_type='playlist',
                item_id='456',
                user_id=user.id,
                priority=1,
            )
            record_id = record.id
            job = queue.get_job(timeout=0.1)
            worker = ImportWorker(app, queue)

            with patch('musicround.helpers.import_queue.ImportHelper.import_item') as mock_import:
                mock_import.return_value = {'imported_count': 3, 'skipped_count': 1}
                worker._process_job(job)

            updated = ImportJobRecord.query.get(record_id)
            assert updated.status == 'completed'
            assert updated.started_at is not None
            assert updated.completed_at is not None
            assert updated.imported_count == 3
            assert updated.skipped_count == 1

    def test_process_job_persists_failure_details(self, app):
        """Test failed imports leave an actionable ImportJobRecord error."""
        with app.app_context():
            user = User(username='failworker', email='failworker@example.com')
            user.password = 'WorkerPass123!'
            db.session.add(user)
            db.session.commit()

            queue = ImportQueue()
            record = enqueue_import_job(
                queue=queue,
                service_name='spotify',
                item_type='playlist',
                item_id='bad',
                user_id=user.id,
                priority=1,
            )
            record_id = record.id
            job = queue.get_job(timeout=0.1)
            worker = ImportWorker(app, queue)

            with patch('musicround.helpers.import_queue.ImportHelper.import_item') as mock_import:
                mock_import.side_effect = RuntimeError('Spotify exploded')
                worker._process_job(job)

            updated = ImportJobRecord.query.get(record_id)
            assert updated.status == 'failed'
            assert updated.completed_at is not None
            assert 'Spotify exploded' in updated.error_message

    def test_process_job_unknown_user_does_not_import(self, app):
        """Test that jobs for missing users are ignored."""
        with app.app_context():
            worker = ImportWorker(app, ImportQueue())
            job = ImportJob(
                priority=1,
                service_name='deezer',
                item_type='track',
                item_id='123',
                user_id=999,
            )

            with patch('musicround.helpers.import_queue.ImportHelper.import_item') as mock_import:
                worker._process_job(job)

            mock_import.assert_not_called()
