# encoding: utf-8
#
# Copyright (C) 2010 Alec Thomas <alec@swapoff.org>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#
# Author: Alec Thomas <alec@swapoff.org>


"""Schema validation for Python data structures.

Given eg. a nested data structure like this:

    {
        'exclude': ['Users', 'Uptime'],
        'include': [],
        'set': {
            'snmp_community': 'public',
            'snmp_timeout': 15,
            'snmp_version': '2c',
        },
        'targets': {
            'localhost': {
                'exclude': ['Uptime'],
                'features': {
                    'Uptime': {
                        'retries': 3,
                    },
                    'Users': {
                        'snmp_community': 'monkey',
                        'snmp_port': 15,
                    },
                },
                'include': ['Users'],
                'set': {
                    'snmp_community': 'monkeys',
                },
            },
        },
    }

A schema like this:

    >>> settings = {
    ...   'snmp_community': str,
    ...   'retries': int,
    ...   'snmp_version': all(coerce(str), any('3', '2c', '1')),
    ... }
    >>> features = ['Ping', 'Uptime', 'Http']
    >>> schema = Schema({
    ...    'exclude': features,
    ...    'include': features,
    ...    'set': settings,
    ...    'targets': {
    ...      'exclude': features,
    ...      'include': features,
    ...      'features': {
    ...        str: settings,
    ...      },
    ...    },
    ... })

Validate like so:

    >>> schema({
    ...   'set': {
    ...     'snmp_community': 'public',
    ...     'snmp_version': '2c',
    ...   },
    ...   'targets': {
    ...     'exclude': ['Ping'],
    ...     'features': {
    ...       'Uptime': {'retries': 3},
    ...       'Users': {'snmp_community': 'monkey'},
    ...     },
    ...   },
    ... })  # doctest: +NORMALIZE_WHITESPACE
    {'set': {'snmp_version': '2c', 'snmp_community': 'public'},
     'targets': {'exclude': ['Ping'],
                 'features': {'Uptime': {'retries': 3},
                              'Users': {'snmp_community': 'monkey'}}}}
"""

import re
import urlparse


__author__ = 'Alec Thomas <alec@swapoff.org>'
__version__ = '0.1'


class Undefined(object):
    def __nonzero__(self):
        return False

    def __repr__(self):
        return '...'


UNDEFINED = Undefined()


class Error(Exception):
    """Base validation exception."""


class SchemaError(Error):
    """An error was encountered in the schema."""


class Invalid(Error):
    """The data was invalid.

    :attr msg: The error message.
    :attr path: The path to the error, as a list of keys in the source data.
    """

    def __init__(self, message, path=None):
        Exception.__init__(self, message)
        self.path = path or []

    @property
    def msg(self):
        return self.args[0]

    def __str__(self):
        path = ' @ data[%s]' % ']['.join(map(repr, self.path)) \
                if self.path else ''
        return Exception.__str__(self) + path


class Schema(object):
    """A validation schema.

    The schema is a Python tree-like structure where nodes are pattern
    matched against corresponding trees of values.

    Nodes can be values, in which case a direct comparison is used, types,
    in which case an isinstance() check is performed, or callables, which will
    validate and optionally convert the value.
    """

    def __init__(self, schema):
        self.schema = schema

    def __call__(self, data):
        return self.validate([], self.schema, data)

    def validate(self, path, schema, data):
        type_ = type(schema)
        if type_ is type:
            type_ = schema
        if type_ is dict:
            return self.validate_dict(path, schema, data)
        elif type_ is list:
            return self.validate_list(path, schema, data)
        elif type_ in (int, long, str, unicode, float, complex, object) \
                or callable(schema):
            return self.validate_scalar(path, schema, data)
        raise SchemaError('unsupported schema data type %r' %
                          type(schema).__name__)

    def validate_dict(self, path, schema, data):
        """Validate a dictionary.

        A dictionary schema can contain a set of values, or at most one
        validator function/type.

        A dictionary schema will only validate a dictionary:

            >>> validate = Schema({})
            >>> validate([])
            Traceback (most recent call last):
            ...
            Invalid: expected a dictionary

        An invalid dictionary value:

            >>> validate = Schema({'one': 'two', 'three': 'four'})
            >>> validate({'one': 'three'})
            Traceback (most recent call last):
            ...
            Invalid: not a valid value for dictionary value @ data['one']

        An invalid key:

            >>> validate({'two': 'three'})
            Traceback (most recent call last):
            ...
            Invalid: not a valid value for dictionary key @ data['two']

        Validation function, in this case the "int" type:

            >>> validate = Schema({'one': 'two', 'three': 'four', int: str})

        Valid integer input:

            >>> validate({10: 'twenty'})
            {10: 'twenty'}

        By default, a "type" in the schema (in this case "int") will be used
        purely to validate that the corresponding value is of that type. It
        will not coerce the value:

            >>> validate({'10': 'twenty'})
            Traceback (most recent call last):
            ...
            Invalid: not a valid value for dictionary key @ data['10']

        Wrap them in the coerce() function to achieve this:

            >>> validate = Schema({'one': 'two', 'three': 'four',
            ...                    coerce(int): str})
            >>> validate({'10': 'twenty'})
            {10: 'twenty'}

        (This is to avoid unexpected surprises.)
        """
        if not isinstance(data, dict):
            raise Invalid('expected a dictionary', path)

        # If the schema dictionary is empty we accept any data dictionary.
        if not schema:
            return data

        out = {}
        invalid = None
        error = None
        for key, value in data.iteritems():
            key_path = path + [key]
            for skey, svalue in schema.iteritems():
                try:
                    new_key = self.validate(key_path, skey, key)
                except Invalid, e:
                    if len(e.path) > len(key_path):
                        raise
                    if not error or len(e.path) > len(error.path):
                        error = e
                    invalid = e.msg + ' for dictionary key'
                    continue
                # Backtracking is not performed after a key is selected, so if
                # the value is invalid we immediately throw an exception.
                try:
                    out[new_key] = self.validate(key_path, svalue, value)
                    break
                except Invalid, e:
                    if len(e.path) > len(key_path):
                        raise
                    raise Invalid(e.msg + ' for dictionary value', e.path)
            else:
                if invalid:
                    if len(error.path) > len(path) + 1:
                        raise error
                    else:
                        raise Invalid(invalid, key_path)
        return out

    def validate_list(self, path, schema, data):
        """Validate a list.

        A list is a sequence of valid values or validators tried in order.

        >>> validator = Schema(['one', 'two', int])
        >>> validator(['one'])
        ['one']
        >>> validator([3.5])
        Traceback (most recent call last):
        ...
        Invalid: invalid list value @ data[0]
        >>> validator([1])
        [1]
        """
        if not isinstance(data, list):
            raise Invalid('expected a list', path)

        # Empty list schema, allow any data list.
        if not schema:
            return data

        out = []
        invalid = None
        index_path = UNDEFINED
        for i, value in enumerate(data):
            index_path = path + [i]
            for s in schema:
                try:
                    out.append(self.validate(index_path, s, value))
                    break
                except Invalid, e:
                    if len(e.path) > len(index_path):
                        raise
                    invalid = e
            else:
                if len(invalid.path) > len(index_path):
                    raise invalid
                else:
                    raise Invalid('invalid list value', index_path)
        return out

    @staticmethod
    def validate_scalar(path, schema, data):
        """A scalar value.

        The schema can either be a value or a type.

        >>> Schema.validate_scalar([], int, 1)
        1
        >>> Schema.validate_scalar([], float, '1')
        Traceback (most recent call last):
        ...
        Invalid: expected float

        Callables have
        >>> Schema.validate_scalar([], lambda v: float(v), '1')
        1.0

        As a convenience, ValueError's are trapped:

        >>> Schema.validate_scalar([], lambda v: float(v), 'a')
        Traceback (most recent call last):
        ...
        Invalid: not a valid value
        """
        if type(schema) is type:
            if not isinstance(data, schema):
                raise Invalid('expected %s' % schema.__name__, path)
        elif callable(schema):
            try:
                return schema(data)
            except ValueError, e:
                raise Invalid('not a valid value', path)
            except Invalid, e:
                raise Invalid(e.msg, path + e.path)
        else:
            if data != schema:
                raise Invalid('not a valid value', path)
        return data


def msg(schema, msg):
    """Report a message if a schema fails to validate.

    >>> validate = Schema(
    ...   msg(['one', 'two', int],
    ...       'should be one of "one", "two" or an integer'))
    >>> validate(['three'])
    Traceback (most recent call last):
    ...
    Invalid: should be one of "one", "two" or an integer

    Messages are only applied to invalid direct descendants of the schema:

    >>> validate = Schema(msg([['one', 'two', int]], 'not okay!'))
    >>> validate([['three']])
    Traceback (most recent call last):
    ...
    Invalid: invalid list value @ data[0][0]
    """
    def f(v):
        try:
            return schema(v)
        except Invalid, e:
            if len(e.path) > 1:
                raise e
            else:
                raise Invalid(msg)
    schema = Schema(schema)
    return f


def coerce(type, msg=None):
    """Coerce a value to a type.

    If the type constructor throws a ValueError, the value will be marked as
    Invalid.
    """
    def f(v):
        try:
            return type(v)
        except ValueError:
            raise Invalid(msg or ('expected %s' % type.__name__))
    return f


def true(msg=None):
    """Assert that a value is true, in the Python sense.

    >>> validate = Schema(true())

    "In the Python sense" means that implicitly false values, such as empty
    lists, dictionaries, etc. are treated as "false":

    >>> validate([])
    Traceback (most recent call last):
    ...
    Invalid: value was not true
    >>> validate([1])
    [1]
    >>> validate(False)
    Traceback (most recent call last):
    ...
    Invalid: value was not true

    ...and so on.
    """
    def f(v):
        if v:
            return v
        raise Invalid(msg or 'value was not true')
    return f


def false(msg=None):
    """Assert that a value is false, in the Python sense.

    (see :func:`true` for more detail)

    >>> validate = Schema(false())
    >>> validate([])
    []
    """
    def f(v):
        if not v:
            return v
        raise Invalid(msg or 'value was not false')
    return f


def boolean(msg=None):
    """Convert human-readable boolean values to a bool.

    Accepted values are 1, true, yes, on, enable, and their negatives.
    Non-string values are cast to bool.

    >>> validate = Schema(boolean())
    >>> validate(True)
    True
    >>> validate('moo')
    Traceback (most recent call last):
    ...
    Invalid: expected boolean
    """
    def f(v):
        try:
            if isinstance(v, basestring):
                v = v.lower()
                if v in ('1', 'true', 'yes', 'on', 'enable'):
                    return True
                if v in ('0', 'false', 'no', 'off', 'disable'):
                    return False
                raise Invalid(msg or 'expected boolean')
            return bool(v)
        except ValueError:
            raise Invalid(msg or 'expected boolean')
    return f


def any(*validators, **kwargs):
    """Use the first validated value.

    :param msg: Message to deliver to user if validation fails.
    :returns: Return value of the first validator that passes.

    >>> validate = Schema(any('true', 'false', all(any(int, bool), coerce(bool))))
    >>> validate('true')
    'true'
    >>> validate(1)
    True
    >>> validate('moo')
    Traceback (most recent call last):
    ...
    Invalid: no valid value found
    """
    msg = kwargs.pop('msg', None)

    def f(v):
        for validator in validators:
            try:
                return Schema.validate_scalar([], validator, v)
            except Invalid:
                pass
        else:
            raise Invalid(msg or 'no valid value found')
    return f


def all(*validators, **kwargs):
    """Value must pass all validators.

    The output of each validator is passed as input to the next.

    :param msg: Message to deliver to user if validation fails.

    >>> validate = Schema(all('10', coerce(int)))
    >>> validate('10')
    10
    """
    msg = kwargs.pop('msg', None)

    def f(v):
        try:
            for validator in validators:
                v = Schema.validate_scalar([], validator, v)
        except Invalid, e:
            raise Invalid(msg or e.msg)
        return v
    return f


def match(pattern, msg=None):
    """Value must match the regular expression.

    >>> validate = Schema(match(r'^0x[A-F0-9]+$'))
    >>> validate('0x123EF4')
    '0x123EF4'
    >>> validate('123EF4')
    Traceback (most recent call last):
    ...
    Invalid: does not match regular expression

    Pattern may also be a compiled regular expression:

    >>> validate = Schema(match(re.compile(r'0x[A-F0-9]+', re.I)))
    >>> validate('0x123ef4')
    '0x123ef4'
    """
    if isinstance(pattern, basestring):
        pattern = re.compile(pattern)

    def f(v):
        if not pattern.match(v):
            raise Invalid(msg or 'does not match regular expression')
        return v
    return f


def sub(pattern, substitution, msg=None):
    """Regex substitution.

    >>> validate = Schema(all(sub('you', 'I'),
    ...                       sub('hello', 'goodbye')))
    >>> validate('you say hello')
    'I say goodbye'
    """
    if isinstance(pattern, basestring):
        pattern = re.compile(pattern)

    def f(v):
        return pattern.sub(substitution, v)
    return f


def url(msg=None):
    """Verify that the value is a URL."""
    def f(v):
        try:
            urlparse.urlparse(v)
            return v
        except:
            raise Invalid(msg or 'expected a URL')
    return f


if __name__ == '__main__':
    import doctest
    doctest.testmod()