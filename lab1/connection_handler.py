import logging
import socket
import threading
from io import BytesIO
import re

from typing import Dict, Tuple
from email.utils import formatdate
from datetime import datetime
from time import mktime


def getNetFormatTime():
    now = datetime.now()
    stamp = mktime(now.timetuple())
    return str(formatdate(timeval=stamp, localtime=False, usegmt=True))


class Cache:
    cache_instance = None

    class Entry:
        def __init__(self, time, data):
            self.time = time
            self.data = data

    @classmethod
    def get_instance(cls):
        if not cls.cache_instance:
            cls.cache_instance = Cache()
        return cls.cache_instance

    def __init__(self):
        self.data: Dict[int, Cache.Entry] = {}

    def __calc_hash(self, host, port, uri) -> int:
        return hash(host + str(port) + uri)

    def get_time(self, host, port, uri):
        data = self.data.get(self.__calc_hash(host, port, uri))
        return data.time if data else None

    def get_data(self, host, port, uri):
        data = self.data.get(self.__calc_hash(host, port, uri))
        return data.data if data else None

    def add(self, host, port, uri, time, data):
        self.data[self.__calc_hash(host, port, uri)] = self.Entry(time, data)


class MethodNotAllowedException(Exception):
    def __init__(self, *args):
        super().__init__(*args)


class RWBufferIO(BytesIO):

    def __init__(self):
        super().__init__()
        self.__readpos = 0

    def write(self, __buffer: bytes):
        self.seek(0, 2)
        return super().write(__buffer)

    def readline(self, **kwargs):
        self.seek(self.__readpos, 0)
        ret_value = super().readline(**kwargs)
        self.__readpos = self.tell()
        return ret_value


class Headers(dict):
    def __init__(self):
        super().__init__()
        self.re_header = re.compile(r"([\w\-]+): ?(.+)\r\n")

    def append_header(self, raw_header: bytes):
        match_header = self.re_header.fullmatch(raw_header.decode('ascii'))
        if not match_header:
            raise ValueError('header invalid: %r' % raw_header)
        self[match_header.group(1)] = match_header.group(2)#.strip()

    def encode(self):
        buffer = BytesIO()
        for key, value in self.items():
            buffer.write(key.encode('ascii') + b': ' + value.encode('ascii') + b'\r\n')
        header_bytes = buffer.getvalue()
        buffer.close()
        return header_bytes


class ConnectionHandler:
    RECV_BUFFER_SIZE = 512 * 1024

    def __init__(self, connection: socket.socket, address, port, logger: logging.Logger = None):
        self.socket = connection
        self.socket.settimeout(5)
        self.address = address
        self.port = port

        if logger is None:
            self.logger = logging.getLogger('ConnectionHandler:' + str(port))
        elif logger is not logging.Logger:
            raise ValueError('logger must be a logging.Logger')
        else:
            self.logger = logger

        self.thread: threading.Thread = None
        self.re_request_line = re.compile(r'([A-Z]+) ([^ ]+) HTTP/([\d.]+)\r\n')
        self.re_host_header = re.compile(r'([\w\-.]+)(:(\d{1,5}))?')

    def run(self):
        self.thread = threading.Thread(target=self.__handler_main())
        self.thread.start()
        return

    def __recv_to_buffer(self, _socket: socket.socket, buffer_io: RWBufferIO) -> int:
        try:
            recv_bytes = _socket.recv(self.RECV_BUFFER_SIZE)
            self.logger.debug(recv_bytes)
        except socket.timeout as e:
            recv_bytes = b''
            self.logger.info('socket timeout')
        buffer_io.write(recv_bytes)
        return len(recv_bytes)

    def __read_line_from_buffer(self, _socket: socket.socket, buffer_io: RWBufferIO) -> bytes:
        line_io = RWBufferIO()
        while True:
            new_bytes = buffer_io.readline()
            line_io.write(new_bytes)
            if new_bytes and new_bytes[-1] == 10:
                return line_io.getvalue()

            if not self.__recv_to_buffer(_socket, buffer_io):
                return b''

    def __send(self, _socket: socket.socket, data: bytes):
        # total_sent = 0
        # data_len = len(data)
        # while total_sent < data_len:
        #     sent = _socket.send(data[total_sent:])
        #     if sent == 0:
        #         raise RuntimeError("socket connection broken")
        #     total_sent = total_sent + sent
        return _socket.sendall(data)

    def __parse_host(self, host: str) -> Tuple[str, int]:
        match_groups = self.re_host_header.fullmatch(host.strip()).groups()
        host = match_groups[0]
        port = match_groups[2] if match_groups[2] else 80
        return host, port

    def __handler_main(self):
        if self.socket.getpeername()[0] == '172.24.151.53':
            self.logger.info('block user')
            self.__send(self.socket, b'HTTP/1.1 403 Forbidden\r\n\r\n')
            self.socket.close()
            return
        try:
            try:
                buffer_io = RWBufferIO()

                request_line = self.__read_line_from_buffer(self.socket, buffer_io)
                self.logger.debug("request_line: %s", request_line)
                if not request_line.strip():
                    self.logger.info('empty request line')
                match_request_line = self.re_request_line.fullmatch(request_line.decode('ascii'))
                method, uri, protocol = match_request_line.groups()

                if method == 'OPTIONS':
                    self.__send(self.socket, b'HTTP/1.1 200 OK\r\n' +
                                b'Allow: OPTIONS, GET, HEAD\r\n\r\n')
                    return
                elif method != 'GET' and method != 'HEAD':
                    raise MethodNotAllowedException()

                self.logger.info(
                    '%s: %s %s' % (self.socket.getpeername(), match_request_line.group(1), match_request_line.group(2)))

                request_headers = Headers()
                while True:
                    header_line = self.__read_line_from_buffer(self.socket, buffer_io)
                    self.logger.debug('header: %s' % header_line)
                    if not header_line.strip():
                        break
                    request_headers.append_header(header_line)
                self.logger.debug(request_headers)
                buffer_io.close()

                # get remote host local_address and local_port from header Host
                remote_host = self.__parse_host(request_headers['Host'])
                if 'mirrors.hit.edu.cn' in remote_host[0]:
                    self.logger.info('phishing')
                    remote_host = ('localhost', 8000)
                    uri = '/'
                if 'jwts.hit.edu.cn' in remote_host[0]:
                    self.logger.info('block site')
                    self.__send(self.socket, b'HTTP/1.1 403 Forbidden')
                    return
                # remove keep-alive header and set connection closed
                request_headers['Connection'] = 'closed'
                request_headers.pop('Keep-Alive', None)

            except MethodNotAllowedException:
                self.logger.info('%s method not allowed' % method)
                self.__send(self.socket, b'HTTP/1.1 405 Method Not Allowed\r\n')
                return
            except Exception as e:
                # raise e
                self.__send(self.socket, b'HTTP/1.1 400 Bad Request\r\n')
                return

            upstream_socket = None
            try:
                cache_instance = Cache.get_instance()
                last_modified_time = cache_instance.get_time(remote_host[0], remote_host[1], uri)
                cached = False
                if last_modified_time:
                    request_headers['If-Modified-Since'] = last_modified_time
                    buffer_io = RWBufferIO()
                    try:
                        upstream_socket = socket.create_connection(remote_host, 5)
                        self.__send(upstream_socket, b'HEAD ' + uri.encode(
                            'ascii') + b' HTTP/1.0\r\n' + b'If-Modified-Since: ' + last_modified_time.encode('ascii') + b'\r\n\r\n')
                        response_line = self.__read_line_from_buffer(upstream_socket, buffer_io)
                        if response_line.split()[1] == b'304':
                            cached = True

                    except:
                        try:
                            buffer_io.close()
                        except:
                            pass
                        try:
                            self.logger.info('socket erorr')
                            upstream_socket.close()
                        except:
                            pass
                else:
                    self.logger.debug('no entry in cache')

                if cached:
                    self.logger.info('cache hit')
                    self.__send(self.socket, cache_instance.get_data(remote_host[0], remote_host[1], uri))
                else:
                    buffer_io = RWBufferIO()
                    try:
                        # create connection to remote host
                        upstream_socket = socket.create_connection(remote_host, 5)
                        self.__send(upstream_socket, (method + ' ' + uri + ' HTTP/1.0\r\n').encode() + request_headers.encode() + b'\r\n')

                        while True:
                            data = upstream_socket.recv(self.RECV_BUFFER_SIZE)
                            buffer_io.write(data)
                            if not data:
                                break
                            self.__send(self.socket, data)

                        if method == 'GET':
                            cache_instance.add(remote_host[0], remote_host[1], uri, getNetFormatTime(),
                                               buffer_io.getvalue())
                    finally:
                        buffer_io.close()
            except socket.timeout:
                self.logger.info('timeout')
            except ConnectionError:
                self.__send(self.socket, b'HTTP/1.1 502 Bad Gateway')
            finally:
                try:
                    self.logger.info('upstream_socket closed')
                    upstream_socket.close()
                except:
                    pass
        finally:
            try:
                self.logger.info('socket closed')
                self.socket.close()

            except:
                pass

    def terminate(self):
        pass
