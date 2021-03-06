"""
This module was taken in part from:
https://github.com/ulule/python-logstash-formatter
"""
import datetime
import json
import logging
import socket
import traceback as tb


def _default_json_default(obj):
    """
    Coerce everything to strings.
    All objects representing time get output as ISO8601.
    """
    if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
        return obj.isoformat()
    else:
        return str(obj)


class LogstashFormatter(logging.Formatter):
    """
    A custom formatter to prepare logs to be
    shipped out to logstash.
    """

    def __init__(
        self, fmt=None, datefmt=None, style="%", json_cls=None, json_default=_default_json_default
    ):
        """
        :param fmt: Config as a JSON string, allowed fields;
               extra: provide extra fields always present in logs
               source_host: override source host name
        :param datefmt: Date format to use (required by logging.Formatter
            interface but not used)
        :param json_cls: JSON encoder to forward to json.dumps
        :param json_default: Default JSON representation for unknown types,
                             by default coerce everything to a string
        """

        if fmt is not None:
            self._fmt = json.loads(fmt)
        else:
            self._fmt = {}
        self.json_default = json_default
        self.json_cls = json_cls
        if "extra" not in self._fmt:
            self.defaults = {}
        else:
            self.defaults = self._fmt["extra"]
        if "source_host" in self._fmt:
            self.source_host = self._fmt["source_host"]
        else:
            try:
                self.source_host = socket.gethostname()
            except Exception:
                self.source_host = ""

    def _record_to_dict(self, record):
        fields = record.__dict__.copy()

        if isinstance(record.msg, dict):
            fields.update(record.msg)
            fields.pop("msg")
            msg = ""
        else:
            msg = record.getMessage()

        try:
            msg = msg.format(**fields)
        except (KeyError, IndexError, ValueError):
            pass
        except Exception:
            # in case we can not format the msg properly we log it as is instead of crashing
            msg = msg

        if "msg" in fields:
            fields.pop("msg")

        if "exc_info" in fields:
            if fields["exc_info"]:
                formatted = tb.format_exception(*fields["exc_info"])
                fields["exception"] = formatted
            fields.pop("exc_info")

        if "exc_text" in fields and not fields["exc_text"]:
            fields.pop("exc_text")

        logr = self.defaults.copy()

        # remove nulls
        fields = {k: v for k, v in fields.items() if v}

        logr.update(
            {
                "@message": msg,
                "@timestamp": datetime.datetime.utcnow().isoformat(),
                "@source_host": self.source_host,
                "@fields": self._build_fields(logr, fields),
            }
        )
        return logr

    def format(self, record):
        """
        Format a log record to JSON, if the message is a dict
        assume an empty message and use the dict as additional
        fields.
        """

        logr = self._record_to_dict(record)
        return json.dumps(logr, default=self.json_default, cls=self.json_cls)

    def _build_fields(self, defaults, fields):
        """Return provided fields including any in defaults
        >>> f = LogstashFormatter()
        # Verify that ``fields`` is used
        >>> f._build_fields({}, {'foo': 'one'}) == \
                {'foo': 'one'}
        True
        # Verify that ``@fields`` in ``defaults`` is used
        >>> f._build_fields({'@fields': {'bar': 'two'}}, {'foo': 'one'}) == \
                {'foo': 'one', 'bar': 'two'}
        True
        # Verify that ``fields`` takes precedence
        >>> f._build_fields({'@fields': {'foo': 'two'}}, {'foo': 'one'}) == \
                {'foo': 'one'}
        True
        """
        return dict(list(defaults.get("@fields", {}).items()) + list(fields.items()))
