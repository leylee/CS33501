import logging
import socket
import threading


class UDPSocket:
    def __init__(self, local_address, local_port, remote_address, remote_port):
        self._local_address = local_address
        self._local_port = local_port
        self._remote_address = remote_address
        self._remote_port = remote_port
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind((local_address, local_port))
        self._socket.connect((remote_address, remote_port))
        self._is_listening_lock = threading.Lock()
        self._is_listening = False
        self._listening_thread: threading.Thread = None
        self.send_lock = threading.Lock()

    def async_recv(self, callback):
        with self._is_listening_lock:
            if self._is_listening:
                raise RuntimeError('UDP socket is already listening')
            self._listening_thread = threading.Thread(target=self._listening_runnable, args=(callback,))
            self._listening_thread.start()
            self._is_listening = True

    def _listening_runnable(self, callback):
        while True:
            buf = self._socket.recv(1500)
            threading.Thread(target=callback, args=(buf,)).start()

    def send(self, data):
        with self.send_lock:
            logging.debug("UDPSocket send: %s", data)
            self._socket.send(data)
