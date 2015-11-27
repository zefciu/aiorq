"""
    aiorq.testing
    ~~~~~~~~~~~~~

    This module implements testing facility for aiorq applications.

    :copyright: (c) 2015 by Artem Malyshev.
    :license: LGPL-3, see LICENSE for more details.
"""

import asyncio
import gc

import aioredis


def async_test(f):
    """Run asynchronous tests inside event loop as coroutines."""

    def wrapper():

        @asyncio.coroutine
        def coroutine(loop):
            redis = yield from aioredis.create_redis(('localhost', 6379), loop=loop)
            try:
                f(redis)
            finally:
                yield from redis.flushdb()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(None)
        loop.run_until_complete(coroutine(loop))
        loop.stop()
        loop.run_forever()
        loop.close()
        gc.collect()
        asyncio.set_event_loop(None)

    return wrapper