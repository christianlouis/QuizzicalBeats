"""Tests for the import queue data structures."""
import pytest
import threading
import time
from musicround.helpers.import_queue import ImportJob, ImportQueue


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
