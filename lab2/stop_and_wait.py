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

    def __init__(self, local_address, local_port, remote_address, remote_port,
                 recv_callback: Callable[[int, bytes], Any], timeout: float = 1, max_datasize: int = 500, loss_rate = 0):

        self.TIMEOUT = timeout
        self.MAX_DATASIZE = max_datasize
        self.SEQ_LENGTH = 1
        self.BYTE_ORDER = 'big'
        self.TXD_PREFIX = b'TXD:'
        self.ACK_PREFIX = b'ACK:'

        # 启动一个 UDPSocket
        self._udp_socket = UDPSocket(local_address, local_port, remote_address, remote_port)

        # 信号量, 用于发送函数的阻塞, 等待接收 ACK
        self._ack_semaphore = threading.BoundedSemaphore(1)
        # 首先需要让可用资源数为零
        self._ack_semaphore.acquire()

        # 连接的总发送包数
        self._total_seq = 0
        # 最后一个发送的报文的 seq
        self._last_send_seq = 0
        # 最后一个接受到的 ACK 的 seq
        self._last_send_ack_seq = -1
        # 最后一个接受到的报文的 seq
        self._last_recv_seq = -1

        # 接收到信息后的回调函数
        self._recv_callback = recv_callback

        # 计算 ACK 长度掩码
        self._seq_mask = (1 << self.SEQ_LENGTH) - 1

        # 发送消息队列
        self._send_queue: Queue[bytes] = Queue()
        self._send_queue_condition = threading.Condition()

        self.random = Random()
        self.loss_rate = loss_rate

        # 启动收发
        self._send_thread = threading.Thread(target=self._send)
        self._send_thread.start()
        self._udp_socket.async_recv(self._recv_handler)

    def _make_txd_packet(self, seq: int, data: bytes) -> bytes:
        return self.TXD_PREFIX + seq.to_bytes(self.SEQ_LENGTH, self.BYTE_ORDER) + data

    def _make_ack_packet(self, seq: int) -> bytes:
        return self.ACK_PREFIX + seq.to_bytes(self.SEQ_LENGTH, self.BYTE_ORDER)

    def send(self, data: bytes):
        with self._send_queue_condition:
            self._send_queue.put(data)
            self._send_queue_condition.notify(1)

    def _send(self):
        while True:
            with self._send_queue_condition:
                # 等待发送队列非空
                while self._send_queue.empty():
                    self._send_queue_condition.wait()
                data = self._send_queue.get()
                logging.debug('notified')
                self._send_queue_condition.notify(1)
                # 将发送的数据拆分成短报文, 以便 UDP 发送
                for seq, data_t in chunks(data, self.MAX_DATASIZE):
                    # 记录当前发送的报文的 seq number
                    self._last_send_seq = self._total_seq & self._seq_mask
                    # 记录超时次数
                    timeout_times = 0
                    while True:
                        self._udp_socket.send(self._make_txd_packet(self._last_send_seq, data_t))
                        # 等待接收 ack 报文
                        if self._ack_semaphore.acquire(blocking=True, timeout=self.TIMEOUT):
                            last_ack_seq = self._last_send_ack_seq
                            if last_ack_seq == self._last_send_seq:
                                break
                            else:
                                logging.info('ack for packet %i mismatch' % last_ack_seq)
                        else:
                            timeout_times += 1
                            logging.info('send %i timed out %i times' % (self._total_seq, timeout_times))
                    self._total_seq += 1

    def _recv_handler(self, data: bytes):
        logging.debug("recieved data: %s" % data)
        # 如果接收到数据报文
        if data.startswith(self.TXD_PREFIX):
            data = data[len(self.TXD_PREFIX):]
            seq = int.from_bytes(data[0:self.SEQ_LENGTH], self.BYTE_ORDER)
            payload = data[self.SEQ_LENGTH:]

            # 模拟丢包
            if self.random.random() < self.loss_rate:
                logging.info("simulating packet loss at seq %d" % seq)
                return

            self._udp_socket.send(self._make_ack_packet(seq))
            if seq != self._last_recv_seq:
                self._last_recv_seq = seq
                self._recv_callback(seq, payload)
        # 如果接收到 ACK 报文
        elif data.startswith(self.ACK_PREFIX):
            data = data[len(self.ACK_PREFIX):]
            seq = int.from_bytes(data[0:self.SEQ_LENGTH], self.BYTE_ORDER)
            self._last_send_ack_seq = seq
            try:
                self._ack_semaphore.release()
            except ValueError:
                pass
        else:
            logging.error("illegal packet")


if __name__ == '__main__':

    def sw_callback(seq, data):
        # print(seq, data)
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


    def test_stop_and_wait():
        logging.basicConfig(level=logging.DEBUG)
        s = StopAndWaitSocket('127.0.0.1', int(sys.argv[1]), '127.0.0.1', int(sys.argv[2]), sw_callback)
        while True:
            buf = sys.stdin.buffer.readline(1000000)
            if not buf:
                break
            s.send(buf)


    test_stop_and_wait()
