import logging
from queue import Queue
from sys import argv
from time import sleep

from stop_and_wait import StopAndWaitSocket

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    queue = Queue()

    def recv_callback(seq, data):
        queue.put(data.decode())

    s = StopAndWaitSocket('127.0.0.1', int(argv[1]), '127.0.0.1', int(argv[2]), recv_callback)
    while True:
        filename = queue.get()
        with open(filename, 'rb') as f:
            while True:
                buf = f.read(1000000)
                if not buf:
                    break
                s.send(buf)

