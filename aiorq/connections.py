"""
    aiorq.connections
    ~~~~~~~~~~~~~~~~~

    This module implement connection resolution mechanism.

    :copyright: (c) 2015 by Artem Malyshev.
    :license: LGPL-3, see LICENSE for more details.
"""

import asyncio
from contextlib import contextmanager

from aioredis import create_redis
from rq.connections import NoRedisConnectionException
from rq.local import LocalStack, release_local


class Connection:
    """All queues created in the inner block will use this connection."""

    def __init__(self, connection=None, **kwargs):

        self.connection = connection
        self.kwargs = kwargs

    def __iter__(self):

        # Make yield from Connection() works.
        if self.connection is None:
            self.connection = yield from create_redis(**self.kwargs)
        return _ConnectionContextManager(self.connection)


@contextmanager
def _ConnectionContextManager(connection):

    push_connection(connection)
    try:
        yield
    finally:
        popped = pop_connection()
        assert popped == connection, \
            'Unexpected Redis connection was popped off the stack. ' \
            'Check your Redis connection setup.'


def pop_connection():
    """Pops the topmost connection from the stack."""

    return _connection_stack.pop()


def push_connection(redis):
    """Pushes the given connection on the stack."""

    _connection_stack.push(redis)


@asyncio.coroutine
def use_connection(redis=None, **kwargs):
    """Clears the stack and uses the given connection.  Protects against
    mixed use of use_connection() and stacked connection contexts.
    """

    assert len(_connection_stack) <= 1, \
        'You should not mix Connection contexts with use_connection()'
    release_local(_connection_stack)

    if redis is None:
        redis = yield from create_redis(**kwargs)
    push_connection(redis)


def get_current_connection():
    """Returns the current Redis connection (i.e. the topmost on the
    connection stack).
    """

    return _connection_stack.top


def resolve_connection(connection=None):
    """Convenience function to resolve the given or the current connection.
    Raises an exception if it cannot resolve a connection now.
    """

    if connection is not None:
        return connection

    connection = get_current_connection()
    if connection is None:
        raise NoRedisConnectionException(
            'Could not resolve a Redis connection')
    return connection


_connection_stack = LocalStack()
