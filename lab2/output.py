import os
import signal
import sys
import threading
from contextlib import contextmanager
import logging
from queue import Queue
from typing import Tuple, Callable, Any

from udp_socket import UDPSocket
from random import Random


@contextmanager
def acquire_timeout(lock, timeout):
    result = lock.acquire(timeout=timeout)
    yield result
    if result:
        lock.release()


def chunks(data, n) -> Tuple[int, bytes]:
    for i in range(0, len(data), n):
        yield i, data[i:i + n]


class StopAndWaitSocket:
    TIMEOUT = 1
    MAX_DATASIZE = 500
    SEQ_LENGTH = 1
    BYTE_ORDER = 'big'

    TXD_PREFIX = b'TXD:'
    ACK_PREFIX = b'ACK:'

    def __init__(self, local_address, local_port, remote_address, remote_port,
                 recv_callback: Callable[[int, bytes], Any]):
        # ???????UDPSocket
        self._udp_socket = UDPSocket(local_address, local_port, remote_address, remote_port)

        # ????? ??????????????, ?????? ACK
        self._ack_semaphore = threading.BoundedSemaphore(1)
        # ???????????????????
        self._ack_semaphore.acquire()

        # ?????????????
        self._total_seq = 0
        # ????????????????seq
        self._last_send_seq = 0
        # ?????????????ACK ??seq
        self._last_send_ack_seq = -1
        # ????????????????? seq
        self._last_recv_seq = -1

        # ?????????????????
        self._recv_callback = recv_callback

        # ??? ACK ??????
        self._seq_mask = (1 << self.SEQ_LENGTH) - 1

        # ??????????
        self._send_queue: Queue[bytes] = Queue()
        self._send_queue_condition = threading.Condition()
