# -*- coding: utf-8 -*-
__version__ = '0.3.2'


from tarantool.connection import Connection
from tarantool.const import *
from tarantool.error import *
from tarantool.const import SOCKET_TIMEOUT


def connect(host='localhost', port=33013, timeout=SOCKET_TIMEOUT):
    """
    Create a connection to the Tarantool server.

    :param str host: Server hostname or IP-address
    :param int port: Server port

    :rtype: :class:`~tarantool.connection.Connection`
    :raise: `NetworkError`
    """

    return Connection(host, port, socket_timeout=timeout)
