import os
import signal
import sys
import threading
from contextlib import contextmanager
import logging
from queue import Queue
from typing import Tuple, Callable, Any, Set, List, Dict

from udp_socket import UDPSocket
from random import Random

import time


@contextmanager
def acquire_timeout(lock, timeout):
    result = lock.acquire(timeout=timeout)
    yield result
    if result:
        lock.release()


def chunks(data, n):
    for i in range(0, len(data), n):
        yield data[i:i + n]


class SRSocket:

    def __init__(self, local_address, local_port, remote_address, remote_port,
                 recv_callback: Callable[[int, bytes], Any], timeout: float = 1, max_datasize: int = 500,
                 seq_length: int = 6, window_size: int = 50, recv_window_size: int = 40):
        self.RECV_WINDOW_SIZE = recv_window_size
        self.TIMEOUT = timeout
        self.MAX_DATASIZE = max_datasize
        self.SEQ_LENGTH = seq_length
        self.WINDOW_SIZE = window_size
        self.BYTE_ORDER = 'big'

        self.TXD_PREFIX = b'TXD:'
        self.ACK_PREFIX = b'ACK:'

        # 启动一个 UDPSocket
        self._udp_socket = UDPSocket(local_address, local_port, remote_address, remote_port)

        # 信号量, 用于发送函数的阻塞, 等待接收 ACK
        self._ack_semaphore = threading.BoundedSemaphore(1)
        # 首先需要让可用资源数为零
        self._ack_semaphore.acquire()

        # 计算 ACK 长度掩码
        self._seq_mask = (1 << self.SEQ_LENGTH) - 1

        # 发送列表的基址
        self.base_index = 0
        # 连接的总发送包数
        self._total_seq = 0
        # 发送窗口首端 seq
        self._send_base_seq = 0
        # 接收到的 ack seq 最大值
        self._last_send_ack_seq = self._seq_mask
        # 最后一个接受到的有效报文的 seq
        self._last_recv_seq = self._seq_mask

        # 接收窗口已经读取的最后一个 seq
        self.last_seq = self._seq_mask
        # 接收窗口的 base seq
        self._recv_base_seq = 0
        # 接收的锁
        self._recv_lock = threading.Lock()

        # 已经发送的分组的时间单调队列
        self._sent_packets_queue: Queue[Tuple[int, float]] = Queue()
        # 接收的分组窗口的集合
        self._recv_packets_set: Dict[int, bytes] = dict()

        # 接收到信息后的回调函数
        self._recv_callback = recv_callback

        # 发送消息队列
        self._send_queue: Queue[bytes] = Queue()
        self._send_queue_condition = threading.Condition()

        # 启动收发
        self._send_thread = threading.Thread(target=self._send)
        self._send_thread.start()
        self._udp_socket.async_recv(self._recv_handler)

        # 随机丢包
        self.random = Random()

    def _calc_seq_delta(self, a, b):
        return (a - b) & self._seq_mask

    def _calc_seq_sum(self, a, b):
        return (a + b) & self._seq_mask

    def _in_send_window(self, seq: int):
        return self._calc_seq_delta(seq, self._send_base_seq) < self.WINDOW_SIZE

    def _in_recv_window(self, seq: int):
        return self._calc_seq_delta(seq, self._recv_base_seq) < self.RECV_WINDOW_SIZE

    def _make_txd_packet(self, seq: int, data: bytes) -> bytes:
        return self.TXD_PREFIX + seq.to_bytes(self.SEQ_LENGTH, self.BYTE_ORDER) + data

    def _make_ack_packet(self, seq: int) -> bytes:
        return self.ACK_PREFIX + seq.to_bytes(self.SEQ_LENGTH, self.BYTE_ORDER)

    def send(self, data: bytes):
        with self._send_queue_condition:
            self._send_queue.put(data)
            self._send_queue_condition.notify(1)

    def _send_packet(self, seq: int, data: bytes):
        self._udp_socket.send(self._make_txd_packet(seq, data))
        self._sent_packets_queue.put((seq, time.time_ns() * 1e-9))

    def _send_packets(self, packets: List[bytes], seq0):
        seq = seq0
        for packet in packets:
            self._send_packet(seq, packet)
            seq = self._calc_seq_sum(seq, 1)

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
                send_list = list(chunks(data, self.MAX_DATASIZE))
                self.base_index = 0

                # 首先发送一个窗口的数据
                self._send_packets(send_list[self.base_index: self.base_index + self.WINDOW_SIZE], self._send_base_seq)

                # 进入循环
                while not self._sent_packets_queue.empty():
                    peek_packet = self._sent_packets_queue.get()
                    # 如果不在窗口里, 证明已经成功发送
                    if not self._in_send_window(peek_packet[0]):
                        continue
                    else:
                        # 计算超时时间
                        timeout = self.TIMEOUT + peek_packet[1] - time.time_ns() * 1e-9

                        # 检查ACK
                        # 先进行一个非阻塞检查
                        new_ack = self._ack_semaphore.acquire(blocking=False)
                        # 如果没有新的 ACK, 且还没有超时, 就等待超时
                        if not new_ack and timeout > 0:
                            new_ack = self._ack_semaphore.acquire(blocking=True, timeout=timeout)

                        # 如果拿到新的 ACK, 则处理
                        if new_ack:
                            # 如果最新的 ACK seq 比 base seq 大, 就更新, 并且发送更多的数据
                            if self._in_send_window(self._last_send_ack_seq):
                                delta = self._calc_seq_delta(self._last_send_ack_seq, self._send_base_seq) + 1
                                # 窗口后移, 并发送新添加的数据
                                if self.base_index + self.WINDOW_SIZE < len(send_list):
                                    self._send_packets(
                                        send_list[
                                        self.base_index + self.WINDOW_SIZE:self.base_index + self.WINDOW_SIZE + delta],
                                        self._calc_seq_sum(self._send_base_seq, self.WINDOW_SIZE))
                                self.base_index += delta
                                self._send_base_seq = self._calc_seq_sum(self._send_base_seq, delta)

                        # 判断 peek_packet seq 是否仍在窗口中, 如果仍在窗口中, 就重发
                        if self._in_send_window(peek_packet[0]):
                            self._send_packet(peek_packet[0], send_list[
                                self.base_index + self._calc_seq_delta(peek_packet[0], self._send_base_seq)])

    def _recv_handler(self, data: bytes):
        logging.debug("recieved data: %s" % data)
        # 如果接收到数据报文
        if data.startswith(self.TXD_PREFIX):
            data = data[len(self.TXD_PREFIX):]
            seq = int.from_bytes(data[0:self.SEQ_LENGTH], self.BYTE_ORDER)
            payload = data[self.SEQ_LENGTH:]

            # 模拟丢包
            # if self.random.random() < 0.5:
            #     logging.info("simulating packet loss at seq %d" % seq)
            #     return

            with self._recv_lock:
                if self._in_recv_window(seq) and seq not in self._recv_packets_set:
                    self._recv_packets_set[seq] = payload
            logging.debug(self._recv_packets_set)
            with self._recv_lock:
                while self._recv_base_seq in self._recv_packets_set:

                    response_data = self._recv_packets_set.pop(self._recv_base_seq)
                    self.last_seq = self._recv_base_seq
                    self._recv_base_seq = self._calc_seq_sum(self._recv_base_seq, 1)
                    self._recv_callback(self.last_seq, response_data)


                # if self._calc_seq_delta(seq, self._last_recv_seq) == 1:
                #     self._last_recv_seq = seq
                #     self._recv_callback(seq, payload)

                self._udp_socket.send(self._make_ack_packet(self.last_seq))
        # 如果接收到 ACK 报文
        elif data.startswith(self.ACK_PREFIX):
            data = data[len(self.ACK_PREFIX):]
            seq = int.from_bytes(data[0:self.SEQ_LENGTH], self.BYTE_ORDER)

            try:
                # 如果 seq 在窗口内, 且:
                #   - 旧的最大 ACK seq 已经不在窗口中, 或
                #   - 都在窗口中, 但 seq 更大
                # 则更新, 并释放锁
                if self._in_send_window(seq) and \
                        (not self._in_send_window(self._last_send_ack_seq) or (
                                self._calc_seq_delta(seq, self._send_base_seq) > self._calc_seq_delta(
                            self._last_send_ack_seq,
                            self._send_base_seq))):
                    self._last_send_ack_seq = seq
                    self._ack_semaphore.release()
            except ValueError:
                pass
        else:
            logging.error("illegal packet")


def sw_callback(seq, data):
    print(seq, data)
    # sys.stdout.buffer.write(data)
    # sys.stdout.buffer.flush()


def test_gbn():
    logging.basicConfig(level=logging.DEBUG)
    s = SRSocket('127.0.0.1', int(sys.argv[1]), '127.0.0.1', int(sys.argv[2]), sw_callback)
    while True:
        buf = sys.stdin.buffer.readline(1000000)
        if not buf:
            break
        s.send(buf)


if __name__ == '__main__':
    # test_gbn()

    logging.basicConfig(level=logging.DEBUG)
    a = SRSocket('127.0.0.1', 8978, '127.0.0.1', 8979, sw_callback)
    b = SRSocket('127.0.0.1', 8979, '127.0.0.1', 8978, sw_callback)
    b.send(b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
    b.send(b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
    b.send(b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
    b.send(b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
