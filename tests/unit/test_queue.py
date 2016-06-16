import asyncio
import pytest
from datetime import datetime

import stubs
import helpers
from aiorq import Queue, get_failed_queue, Worker
from aiorq.exceptions import InvalidJobOperationError, DequeueTimeout
from aiorq.job import Job
from aiorq.specs import JobStatus
from aiorq.utils import unset, utcformat, utcnow
from fixtures import say_hello, Number, echo, div_by_zero, CustomJob


def test_create_queue():
    """We can create queue instance."""

    q = Queue()
    assert q.name == 'default'


def test_create_named_queue():
    """We can create named queue instance."""

    q = Queue('my-queue')
    assert q.name == 'my-queue'


def test_queue_magic_methods():
    """Test simple magic method behavior of the Queue class."""

    q = Queue()
    assert hash(q) == hash('default')
    assert str(q) == "<Queue 'default'>"
    assert repr(q) == "Queue('default')"


def test_custom_job_class():
    """Ensure custom job class assignment works as expected."""

    q = Queue(job_class=CustomJob)
    assert q.job_class == CustomJob


def test_custom_job_string():
    """Ensure custom job string assignment works as expected."""

    q = Queue(job_class='fixtures.CustomJob')
    assert q.job_class == CustomJob


def test_equality():
    """Mathematical equality of queues."""

    q1 = Queue('foo')
    q2 = Queue('foo')
    q3 = Queue('bar')
    assert q1 == q2
    assert q2 == q1
    assert q1 != q3
    assert q2 != q3


def test_queue_order():
    """Mathematical order of queues."""

    q1 = Queue('a')
    q2 = Queue('b')
    q3 = Queue('c')
    assert q1 < q2
    assert q3 > q2


def test_empty_queue():
    """Emptying queues."""

    redis = object()

    class Protocol:
        @staticmethod
        @asyncio.coroutine
        def empty_queue(connection, name):
            assert connection is redis
            assert name == 'example'
            return 2

    class TestQueue(Queue):
        protocol = Protocol()

    q = TestQueue('example', connection=redis)
    assert (yield from q.empty()) == 2


def test_queue_is_empty():
    """Detecting empty queues."""

    redis = object()
    lengths = [2, 0]

    class Protocol:
        @staticmethod
        @asyncio.coroutine
        def queue_length(connection, name):
            assert connection is redis
            assert name == 'example'
            return lengths.pop(0)

    class TestQueue(Queue):
        protocol = Protocol()

    q = TestQueue('example', connection=redis)
    assert not (yield from q.is_empty())
    assert (yield from q.is_empty())


def test_queue_count():
    """Count all messages in the queue."""

    redis = object()

    class Protocol:
        @staticmethod
        @asyncio.coroutine
        def queue_length(connection, name):
            assert connection is redis
            assert name == 'example'
            return 3

    class TestQueue(Queue):
        protocol = Protocol()

    q = TestQueue('example', connection=redis)
    assert (yield from q.count) == 3


def test_remove():
    """Ensure queue.remove properly removes Job from queue."""

    redis = object()
    sentinel = []

    class Protocol:
        @staticmethod
        @asyncio.coroutine
        def cancel_job(connection, name, id):
            assert connection is redis
            assert name == 'example'
            assert id == '56e6ba45-1aa3-4724-8c9f-51b7b0031cee'
            sentinel.append(1)

    class TestQueue(Queue):
        protocol = Protocol()

    q = TestQueue('example', connection=redis)

    job = Job(
        connection=redis,
        id='56e6ba45-1aa3-4724-8c9f-51b7b0031cee',
        func=say_hello,
        args=(),
        kwargs={},
        description='fixtures.say_hello()',
        timeout=180,
        result_ttl=5000,
        origin='default',
        created_at=datetime(2016, 4, 5, 22, 40, 35))

    yield from q.remove(job)
    yield from q.remove(job.id)
    assert len(sentinel) == 2


def test_jobs():
    """Getting jobs out of a queue."""

    redis = object()

    class Protocol:
        @staticmethod
        @asyncio.coroutine
        def jobs(connection, queue, start, end):
            assert connection is redis
            assert queue == 'example'
            assert start == 0
            assert end == -1
            return [stubs.job_id.encode()]

        @staticmethod
        @asyncio.coroutine
        def job(connection, id):
            assert connection is redis
            assert id == stubs.job_id
            return {
                b'created_at': b'2016-04-05T22:40:35Z',
                b'data': b'\x80\x04\x950\x00\x00\x00\x00\x00\x00\x00(\x8c\x19fixtures.some_calculation\x94NK\x03K\x04\x86\x94}\x94\x8c\x01z\x94K\x02st\x94.',  # noqa
                b'description': b'fixtures.some_calculation(3, 4, z=2)',
                b'timeout': 180,
                b'result_ttl': 5000,
                b'status': JobStatus.QUEUED.encode(),
                b'origin': stubs.queue.encode(),
                b'enqueued_at': utcformat(utcnow()).encode(),
            }

    class TestQueue(Queue):
        protocol = Protocol()

    q = TestQueue('example', connection=redis)
    [job] = yield from q.jobs
    assert job.connection is redis
    assert job.id == stubs.job_id
    assert job.description == stubs.job['description']


# TODO: test q.jobs and empty hash from protocol.job
# TODO: test get_job_ids offset and length behavior.


def test_compact():
    """Queue.compact() removes non-existing jobs."""

    pass                        # TODO: write actual test


def test_enqueue():
    """Enqueueing job onto queues."""

    connection = object()
    uuids = []

    class Protocol:
        @staticmethod
        @asyncio.coroutine
        def enqueue_job(redis, queue, id, data, description, timeout,
                        created_at, *, result_ttl=unset, dependency_id=unset,
                        at_front=False):
            assert redis is connection
            assert queue == 'example'
            assert isinstance(id, str)
            assert data == b'\x80\x04\x952\x00\x00\x00\x00\x00\x00\x00(\x8c\x12fixtures.say_hello\x94N\x8c\x04Nick\x94\x85\x94}\x94\x8c\x03foo\x94\x8c\x03bar\x94st\x94.' # noqa
            assert description == "fixtures.say_hello('Nick', foo='bar')"
            assert timeout == 180
            assert created_at == utcformat(utcnow())
            assert result_ttl is unset
            assert dependency_id is unset
            assert at_front is False
            uuids.append(id)
            return JobStatus.QUEUED, utcnow()

    class TestQueue(Queue):
        protocol = Protocol()

    q = TestQueue('example', connection=connection)

    job = yield from q.enqueue(say_hello, 'Nick', foo='bar')

    assert job.connection is connection
    assert job.id == uuids.pop(0)
    assert job.func == say_hello
    assert job.args == ('Nick',)
    assert job.kwargs == {'foo': 'bar'}
    assert job.description == "fixtures.say_hello('Nick', foo='bar')"
    assert job.timeout == 180
    assert job.result_ttl == None  # TODO: optional?
    assert job.origin == q.name
    assert helpers.strip_microseconds(job.created_at) == helpers.strip_microseconds(utcnow())
    assert helpers.strip_microseconds(job.enqueued_at) == helpers.strip_microseconds(utcnow())
    assert job.status == JobStatus.QUEUED
    assert job.dependency_id is None


def test_enqueue_call():
    """Enqueueing job onto queues."""

    connection = object()
    uuids = []

    class Protocol:
        @staticmethod
        @asyncio.coroutine
        def enqueue_job(redis, queue, id, data, description, timeout,
                        created_at, *, result_ttl=unset, dependency_id=unset,
                        at_front=False):
            assert redis is connection
            assert queue == 'example'
            assert isinstance(id, str)
            assert data == b'\x80\x04\x952\x00\x00\x00\x00\x00\x00\x00(\x8c\x12fixtures.say_hello\x94N\x8c\x04Nick\x94\x85\x94}\x94\x8c\x03foo\x94\x8c\x03bar\x94st\x94.' # noqa
            assert description == "fixtures.say_hello('Nick', foo='bar')"
            assert timeout == 180
            assert created_at == utcformat(utcnow())
            assert result_ttl is unset
            assert dependency_id is unset
            assert at_front is False
            uuids.append(id)
            return JobStatus.QUEUED, utcnow()

    class TestQueue(Queue):
        protocol = Protocol()

    q = TestQueue('example', connection=connection)

    job = yield from q.enqueue_call(say_hello, args=('Nick',), kwargs={'foo': 'bar'})

    assert job.connection is connection
    assert job.id == uuids.pop(0)
    assert job.func == say_hello
    assert job.args == ('Nick',)
    assert job.kwargs == {'foo': 'bar'}
    assert job.description == "fixtures.say_hello('Nick', foo='bar')"
    assert job.timeout == 180
    assert job.result_ttl == None  # TODO: optional?
    assert job.origin == q.name
    assert helpers.strip_microseconds(job.created_at) == helpers.strip_microseconds(utcnow())
    assert helpers.strip_microseconds(job.enqueued_at) == helpers.strip_microseconds(utcnow())
    assert job.status == JobStatus.QUEUED
    assert job.dependency_id is None


# TODO: enqueue_call with dependency job
# TODO: enqueue_call with dependency string id
# TODO: no args
# TODO: no kwargs
# TODO: timeout calculation
# TODO: test default_timeout setup
# TODO: custom description
# TODO: meta field
# TODO: test_requeue_job
# TODO: test_requeue_nonfailed_job_fails
# Failed queue tests.
# TODO: test_quarantine_preserves_timeout
# TODO: test_requeueing_preserves_timeout
# TODO: test_requeue_sets_status_to_queued

# TODO: synchronize protocol stubs with actual protocol implementation
