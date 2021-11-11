import logging

from stop_and_wait import StopAndWaitSocket



if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    def recv_callback(seq, data):
        print(seq, data.decode())

    s = StopAndWaitSocket('127.0.0.1', 7789, '127.0.0.1', 7790, recv_callback, loss_rate=0.5, max_datasize=10)
    r = StopAndWaitSocket('127.0.0.1', 7790, '127.0.0.1', 7789, recv_callback, loss_rate=0.5, max_datasize=10)

    s.send(b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
    s.send(b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
    s.send(b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
    s.send(b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')


