import logging
from queue import Queue
from sys import argv
from time import sleep

from stop_and_wait import StopAndWaitSocket

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)


    def recv_callback(seq, data):
        with open('1.py', 'ab') as f:
            f.write(data)


    s = StopAndWaitSocket('127.0.0.1', int(argv[1]), '127.0.0.1', int(argv[2]), recv_callback)
    s.send(argv[3].encode())
    while True:
        sleep(2)


