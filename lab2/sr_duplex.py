from sr import SRSocket
from sys import argv



if __name__ == '__main__':
    def recv_callback(seq, data):
        print(seq, data.decode())

    s = SRSocket('127.0.0.1', int(argv[1]), '127.0.0.1', int(argv[2]), recv_callback)
    while True:
        s.send(input().encode())

