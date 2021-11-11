import logging
import socket
import threading

from typing import List

from connection_handler import ConnectionHandler


class HttpProxy:
    def __init__(self, port: int = 8080, address: str = 'localhost', logger: logging.Logger = None):
        try:
            self.port = int(port)
            assert 1024 <= self.port <= 65535
        except (ValueError, AssertionError):
            raise ValueError('local_port must in range [1024, 65535]')

        try:
            socket.gethostbyname(address)
            self.address = address
        except OSError:
            raise ValueError('hostname invalid: %s' % address)

        if logger is None:
            self.logger = logging.getLogger('HttpProxy')
        elif logger is not logging.Logger:
            raise ValueError('logger must be a logging.Logger')
        else:
            self.logger = logger

        self.active = False
        self.__listening_thread = None
        self.connections = []
        self.connection_handlers: List[ConnectionHandler] = []

    def activate(self):
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
            server_socket.bind((self.address, self.port))
            server_socket.listen(100)
            self.__listening_thread = threading.Thread(target=self.__listen_runnable,
                                                       kwargs={'server_socket': server_socket})
            self.__listening_thread.start()
            self.logger.info('proxy server listening on %s:%i' % (self.address, self.port))
        except Exception as e:
            raise e

    def __listen_runnable(self, server_socket: socket.socket):
        while True:
            connection, address = server_socket.accept()
            self.logger.info('accepted connection: %s:%d' % (address[0], address[1]))
            connection_handler = ConnectionHandler(connection, address[0], address[1])
            self.connection_handlers.append(connection_handler)
            connection_handler.run()

    def deactivate(self):
        for connection_handler in self.connection_handlers:
            connection_handler.terminate()