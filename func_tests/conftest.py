import os
import signal
import subprocess
import threading
import time

import pytest
import redis


@pytest.yield_fixture
def flush_redis():

    yield
    connection = redis.StrictRedis()
    connection.flushdb()


@pytest.fixture
def worker():

    return Worker()


class Worker:

    command = ['aiorq', 'worker', 'foo']
    stop_interval = 0.5
    kill_after = 300

    def __init__(self):

        self.process = None
        self.is_running = False
        self.start()
        self.schedule_kill()

    def start(self):

        self.process = subprocess.Popen(
            args=self.command, env=self.environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.is_running = True

    def stop_with(self, *signals):

        self.schedule_stop(signals)
        self.wait()
        self.is_running = False

    def schedule_stop(self, signals):

        for generation, signum in enumerate(signals, 1):
            timeout = self.stop_interval * generation
            thread = threading.Thread(target=self.send, args=(signum, timeout))
            thread.start()

    def schedule_kill(self):

        thread = threading.Thread(target=self.kill)
        thread.start()

    def wait(self):

        stdout, stderr = self.process.communicate()
        print(stdout.decode())
        print(stderr.decode())

    def send(self, signum, sleep_for):

        time.sleep(sleep_for)
        self.process.send_signal(signum)

    def kill(self):

        time.sleep(self.kill_after)
        if self.is_running:
            self.send(signal.SIGKILL, 0)

    @property
    def environment(self):

        environment = os.environ.copy()
        environment['PYTHONPATH'] = self.pythonpath
        return environment

    @property
    def pythonpath(self):

        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'fixtures')

    @property
    def returncode(self):

        return self.process.returncode