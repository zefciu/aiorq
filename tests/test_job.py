from datetime import datetime

import pytest
from rq.utils import utcformat

from aiorq.job import Job, loads, dumps
from aiorq.exceptions import NoSuchJobError
from testing import async_test
from fixtures import Number, some_calculation, say_hello, CallableObject
from helpers import strip_microseconds


@async_test
def test_unicode(**kwargs):
    """Unicode in job description."""

    job = Job.create('myfunc', args=[12, "☃"],
                     kwargs=dict(snowman="☃", null=None))
    expected_string = "myfunc(12, '☃', null=None, snowman='☃')"
    assert job.description, expected_string


@async_test
def test_create_empty_job(**kwargs):
    """Creation of new empty jobs."""

    job = Job()

    # Jobs have a random UUID and a creation date
    assert job.id
    assert job.created_at

    # ...and nothing else
    assert not job.origin
    assert not job.enqueued_at
    assert not job.started_at
    assert not job.ended_at
    assert not (yield from job.result)
    assert not job.exc_info

    with pytest.raises(ValueError):
        job.func
    with pytest.raises(ValueError):
        job.instance
    with pytest.raises(ValueError):
        job.args
    with pytest.raises(ValueError):
        job.kwargs


@async_test
def test_create_typical_job(**kwargs):
    """Creation of jobs for function calls."""
    job = Job.create(func=some_calculation,
                     args=(3, 4), kwargs=dict(z=2))

    # Jobs have a random UUID
    assert job.id
    assert job.created_at
    assert job.description
    assert not job.instance

    # Job data is set...
    assert job.func == some_calculation
    assert job.args == (3, 4)
    assert job.kwargs == {'z': 2}

    # ...but metadata is not
    assert not job.origin
    assert not job.enqueued_at
    assert not (yield from job.result)


@async_test
def test_create_instance_method_job(**kwargs):
    """Creation of jobs for instance methods."""

    n = Number(2)
    job = Job.create(func=n.div, args=(4,))

    # Job data is set
    assert job.func == n.div
    assert job.instance == n
    assert job.args == (4,)


@async_test
def test_create_job_from_string_function(**kwargs):
    """Creation of jobs using string specifier."""

    job = Job.create(func='fixtures.say_hello', args=('World',))

    # Job data is set
    assert job.func == say_hello
    assert not job.instance
    assert job.args == ('World',)


@async_test
def test_create_job_from_callable_class(**kwargs):
    """Creation of jobs using a callable class specifier."""

    kallable = CallableObject()
    job = Job.create(func=kallable)

    assert job.func == kallable.__call__
    assert job.instance == kallable


@async_test
def test_job_properties_set_data_property(**kwargs):
    """Data property gets derived from the job tuple."""

    job = Job()
    job.func_name = 'foo'
    fname, instance, args, kwargs = loads(job.data)

    assert fname == job.func_name
    assert not instance
    assert args == ()
    assert kwargs == {}


@async_test
def test_data_property_sets_job_properties(**kwargs):
    """Job tuple gets derived lazily from data property."""

    job = Job()
    job.data = dumps(('foo', None, (1, 2, 3), {'bar': 'qux'}))

    assert job.func_name == 'foo'
    assert not job.instance
    assert job.args == (1, 2, 3)
    assert job.kwargs == {'bar': 'qux'}


@async_test
def test_save(redis, **kwargs):
    """Storing jobs."""

    job = Job.create(func=some_calculation, args=(3, 4), kwargs=dict(z=2))

    # Saving creates a Redis hash
    assert not (yield from redis.exists(job.key))
    yield from job.save()
    assert (yield from redis.type(job.key)) == b'hash'

    # Saving writes pickled job data
    unpickled_data = loads((yield from redis.hget(job.key, 'data')))
    assert unpickled_data[0] == 'fixtures.some_calculation'


@async_test
def test_fetch(redis, **kwargs):
    """Fetching jobs."""

    yield from redis.hset('rq:job:some_id', 'data',
                          "(S'fixtures.some_calculation'\n"
                          "N(I3\nI4\nt(dp1\nS'z'\nI2\nstp2\n.")
    yield from redis.hset('rq:job:some_id', 'created_at',
                          '2012-02-07T22:13:24Z')

    # Fetch returns a job
    job = yield from Job.fetch('some_id')

    assert job.id == 'some_id'
    assert job.func_name == 'fixtures.some_calculation'
    assert not job.instance
    assert job.args == (3, 4)
    assert job.kwargs == dict(z=2)
    assert job.created_at == datetime(2012, 2, 7, 22, 13, 24)


@async_test
def test_persistence_of_empty_jobs(**kwargs):
    """Storing empty jobs."""

    job = Job()
    with pytest.raises(ValueError):
        yield from job.save()


@async_test
def test_persistence_of_typical_jobs(redis, **kwargs):
    """Storing typical jobs."""

    job = Job.create(func=some_calculation, args=(3, 4), kwargs=dict(z=2))
    yield from job.save()

    expected_date = strip_microseconds(job.created_at)
    stored_date = (yield from redis.hget(job.key, 'created_at')) \
        .decode('utf-8')
    assert stored_date == utcformat(expected_date)

    # ... and no other keys are stored
    assert sorted((yield from redis.hkeys(job.key))) \
        == [b'created_at', b'data', b'description']


@async_test
def test_persistence_of_parent_job(**kwargs):
    """Storing jobs with parent job, either instance or key."""

    parent_job = Job.create(func=some_calculation)
    yield from parent_job.save()

    job = Job.create(func=some_calculation, depends_on=parent_job)
    yield from job.save()

    stored_job = yield from Job.fetch(job.id)
    assert stored_job._dependency_id == parent_job.id
    assert (yield from stored_job.dependency) == parent_job

    job = Job.create(func=some_calculation, depends_on=parent_job.id)
    yield from job.save()
    stored_job = yield from Job.fetch(job.id)

    assert stored_job._dependency_id == parent_job.id
    assert (yield from stored_job.dependency) == parent_job


@async_test
def test_store_then_fetch(**kwargs):
    """Store, then fetch."""

    job = Job.create(func=some_calculation, args=(3, 4), kwargs=dict(z=2))
    yield from job.save()

    job2 = yield from Job.fetch(job.id)
    assert job.func == job2.func
    assert job.args == job2.args
    assert job.kwargs == job2.kwargs

    # Mathematical equation
    assert job == job2


@async_test
def test_fetching_can_fail(**kwargs):
    """Fetching fails for non-existing jobs."""

    with pytest.raises(NoSuchJobError):
        yield from Job.fetch('b4a44d44-da16-4620-90a6-798e8cd72ca0')