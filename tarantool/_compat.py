import sys


PY3 = sys.version_info[0] == 3

if PY3:
    basestring = str
    unicode = str
    bytes = bytes
    long = int
else:
    basestring = basestring
    unicode = unicode
    bytes = str
    long = long
