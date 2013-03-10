# -*- coding: utf-8 -*-
import struct
import sys

from six import integer_types, PY3

from tarantool.const import (
    struct_L, struct_Q, REQUEST_TYPE_SELECT,
    REQUEST_TYPE_INSERT, REQUEST_TYPE_DELETE, REQUEST_TYPE_UPDATE
)
from tarantool.error import DatabaseError


if PY3:
    unicode = str
    to_ord = lambda a: a
else:
    to_ord = ord


class field(bytes):
    """
    Represents a single element of the Tarantool's tuple
    """
    def __new__(cls, value):
        """
        Create new instance of Tarantool field (single tuple element)
        """
        # Since parent class is immutable, we should
        # override __new__, not __init__
        if isinstance(value, unicode):
            return super(field, cls).__new__(
                cls, value.encode('utf-8', 'replace')
            )

        if sys.version_info.major < 3 and isinstance(value, str):
            return super(field, cls).__new__(cls, value)

        if isinstance(value, (bytearray, bytes)):
            return super(field, cls).__new__(cls, value)

        if isinstance(value, integer_types):
            if 0 <= value <= 0xFFFFFFFF:
                # 32 bit integer
                return super(field, cls).__new__(cls, struct_L.pack(value))
            elif 0xFFFFFFFF < value <= 0xFFFFFFFFFFFFFFFF:
                # 64 bit integer
                return super(field, cls).__new__(cls, struct_Q.pack(value))
            else:
                raise ValueError('Integer argument out of range')

        # NOTE: It is posible to implement float
        raise TypeError('Unsupported argument type %s' % (
            type(value).__name__)
        )

    def __int__(self):
        """Cast field to int"""
        if len(self) == 4:
            return struct_L.unpack(self)[0]
        elif len(self) == 8:
            return struct_Q.unpack(self)[0]
        else:
            raise ValueError('Unable to cast field to int: length must be '
                             '4 or 8 bytes, field length is %d' % len(self))

    if sys.version_info.major > 2:
        def __str__(self):
            """Cast field to str"""
            return self.decode('utf-8', 'replace')
    else:
        def __unicode__(self):
            """Cast field to unicode"""
            return self.decode('utf-8', 'replace')


class Response(list):
    """
    Represents a single response from the server in compliance with the
    Tarantool protocol.
    Responsible for data encapsulation (i.e. received list of tuples)
    and parses binary packet received from the server.
    """

    def __init__(self, header, body, field_types=None):
        """
        Create an instance of `Response` using data received from the server.

        __init__() itself reads data from the socket, parses response body and
        sets appropriate instance attributes.

        :param header: header of the response
        :type header: array of bytes
        :param body: body of the response
        :type body: array of bytes
        """

        # This is not necessary, because underlying list data structures
        # are created in the __new__(). But let it be.
        super(Response, self).__init__()

        self._body_length = None
        self._request_id = None
        self._request_type = None
        self._completion_status = None
        self._return_code = None
        self._return_message = None
        self._rowcount = None
        self.field_types = field_types

        # Unpack header
        (self._request_type, self._body_length,
            self._request_id) = struct.unpack('<LLL', header)

        if body:
            self._unpack_body(body)

    @staticmethod
    def _unpack_int_base128(varint, offset):
        """Implement Perl unpack's 'w' option, aka base 128 decoding."""
        res = to_ord(varint[offset])
        if to_ord(varint[offset]) >= 0x80:
            offset += 1
            res = ((res - 0x80) << 7) + to_ord(varint[offset])
            if to_ord(varint[offset]) >= 0x80:
                offset += 1
                res = ((res - 0x80) << 7) + to_ord(varint[offset])
                if to_ord(varint[offset]) >= 0x80:
                    offset += 1
                    res = ((res - 0x80) << 7) + to_ord(varint[offset])
                    if to_ord(varint[offset]) >= 0x80:
                        offset += 1
                        res = ((res - 0x80) << 7) + to_ord(varint[offset])
        return res, offset + 1

    def _unpack_tuple(self, buff):
        """
        Unpacks the tuple from byte buffer
        <tuple> ::= <cardinality><field>+

        :param buff: byte array of the form <cardinality><field>+
        :type buff: ctypes buffer or bytes

        :return: tuple of unpacked values
        :rtype: tuple
        """

        cardinality = struct_L.unpack_from(buff)[0]
        _tuple = [''] * cardinality
        # The first 4 bytes in the response body
        # is the <count> we have already read
        offset = 4
        for i in range(cardinality):
            field_size, offset = self._unpack_int_base128(buff, offset)
            field_data = struct.unpack_from('<%ds' % field_size, buff, offset)
            _tuple[i] = field(field_data[0])
            offset += field_size

        return tuple(_tuple)

    def _unpack_body(self, buff):
        """
        Parse the response body.
        After body unpacking its data available as python list of tuples

        For each request type the response body has the same format:
        <insert_response_body> ::= <count> | <count><fq_tuple>
        <update_response_body> ::= <count> | <count><fq_tuple>
        <delete_response_body> ::= <count> | <count><fq_tuple>
        <select_response_body> ::= <count><fq_tuple>*
        <call_response_body>   ::= <count><fq_tuple>

        :param buff: buffer containing request body
        :type byff: ctypes buffer
        """

        # Unpack <return_code>
        self._return_code = struct.unpack_from('<L', buff, offset=0)[0]

        # Separate return_code and completion_code
        self._completion_status = self._return_code & 0x00ff
        self._return_code = self._return_code >> 8

        # In case of an error unpack the body as an error message
        if self._return_code != 0:
            self._return_message = unicode(buff[4:-1], 'utf8', 'replace')
            if self._completion_status == 2:
                raise DatabaseError(self._return_code, self._return_message)

        # If the response don't contains any tuples - there is
        # no tuples to unpack
        if self._body_length == 8:
            return

        # Unpack <count> (how many records affected or selected)
        self._rowcount = struct.unpack_from('<L', buff, offset=4)[0]

        # Parse response tuples (<fq_tuple>)
        if self._rowcount > 0:
            # The first 4 bytes in the response body
            # is the <count> we have already read
            offset = 8
            while offset < self._body_length:
                # In response tuples have the form
                # <size><tuple> (<fq_tuple> ::= <size><tuple>).
                # Attribute <size> takes into account only size of tuple's
                # <field> payload, but does not include 4-byte of
                # <cardinality> field.
                # Therefore the actual size of the <tuple> is greater
                # to 4 bytes.
                tuple_size = struct.unpack_from('<L', buff, offset)[0] + 4
                tuple_data = struct.unpack_from(
                    '<%ds' % (tuple_size), buff, offset + 4)[0]
                tuple_value = self._unpack_tuple(tuple_data)
                if self.field_types:
                    self.append(self._cast_tuple(tuple_value))
                else:
                    self.append(tuple_value)
                # This '4' is a size of <size> attribute
                offset = offset + tuple_size + 4

    @property
    def completion_status(self):
        """
        :type: int

        Request completion status.

        There are only three completion status codes in use:

            * ``0`` -- "success"; the only possible :attr:`return_code`
              with this status is ``0``
            * ``1`` -- "try again"; an indicator of an intermittent error.
              This status is handled automatically by this module.
            * ``2`` -- "error"; in this case :attr:`return_code` holds
              the actual error.
        """
        return self._completion_status

    @property
    def rowcount(self):
        """
        :type: int

        Number of rows affected or returned by a query.
        """
        return self._rowcount

    @property
    def return_code(self):
        """
        :type: int

        Required field in the server response.
        Value of :attr:`return_code` can be ``0`` if request was sucessfull
        or contains an error code.
        If :attr:`return_code` is non-zero than :attr:`return_message`
        contains an error message.
        """
        return self._return_code

    @property
    def return_message(self):
        """
        :type: str

        The error message returned by the server in case of
        :attr:`return_code` is non-zero.
        """
        return self._return_message

    @staticmethod
    def _cast_field(cast_to, value):
        """
        Convert field type from raw bytes to native python type

        :param cast_to: native python type to cast to
        :type cast_to: a type object (one of bytes, int,
            unicode (str for py3k))
        :param value: raw value from the database
        :type value: bytes

        :return: converted value
        :rtype: value of native python type (one of bytes, int,
            unicode (str for py3k))
        """

        if cast_to in (int, unicode):
            return cast_to(value)
        elif cast_to in (any, bytes):
            return value
        else:
            raise TypeError('Invalid field type %s' % cast_to)

    def _cast_tuple(self, values):
        """
        Convert values of the tuple from raw bytes to native python types

        :param values: tuple of the raw database values
        :type value: tuple of bytes

        :return: converted tuple value
        :rtype: value of native python types (bytes, int,
            unicode (or str for py3k))
        """
        result = []
        for i, value in enumerate(values):
            if i < len(self.field_types):
                result.append(self._cast_field(self.field_types[i], value))
            else:
                result.append(self._cast_field(self.field_types[-1], value))

        return tuple(result)

    def __repr__(self):
        """
        Return user friendy string representation of the object.
        Useful for the interactive sessions and debuging.

        :rtype: str or None
        """
        # If response is not empty then return default list representation
        # If there was an SELECT request - return list representation
        # even it is empty
        if(self._request_type == REQUEST_TYPE_SELECT or len(self)):
            return super(Response, self).__repr__()

        # Return string of form "N records affected"
        reqs = {
            REQUEST_TYPE_DELETE: 'deleted',
            REQUEST_TYPE_INSERT: 'inserted',
            REQUEST_TYPE_UPDATE: 'updated'
        }

        affected = '%s record%s %s' % (
            self.rowcount,
            's'[self.rowcount == 1:],
            reqs.get(self._request_type, 'affected')
        )
        return affected
