from http_proxy import HttpProxy
from time import sleep
import logging


def test():
    logging.basicConfig(level=logging.DEBUG)
    HttpProxy(address='', port=8080).activate()
    while True:
        sleep(10)


if __name__ == '__main__':
    test()
