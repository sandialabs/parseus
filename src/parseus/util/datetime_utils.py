"Utilities for managing datetimes"

from datetime import datetime, timezone

DATETIME_FMT_STR = "%Y-%m-%dT%H:%M:%S.%fZ"


def make_zulu_time(timestamp: datetime = None, **kwargs) -> str:
    """
    Converts either a datetime object or a list of date parameters to a
    string in the same format as accepted by Elasticsearch, e.g. "2017-08-28T19:37:43.354Z".

    :param datetime timestamp: A datetime object. If not specified, the fields in `kwargs`
                               will be used.
    :param kwargs: Passed to the constructor of `datetime.datetime`. Only used if
                   :code:`timestamp is None`.
    :return: zulu time example - 2017-08-28T19:37:43.354Z
    """
    # (year, month=01, day=01, hour=00, min=00,second=00, millisecond=000):
    if timestamp is None and not kwargs:
        # no input was passed
        return None

    if timestamp:
        return timestamp.strftime(DATETIME_FMT_STR)

    return datetime(**kwargs).strftime(DATETIME_FMT_STR)


def datetime_parser(datetime_str: str) -> datetime:
    """
    Parses a string representation of a datetime (e.g. "2017-08-28T19:37:43.354Z")
    into a datetime object.

    This is the inverse of :func:`make_zulu_time`.

    :param str datetime_str: The string representation of the datetime object. It can
                             also be any other object that can be parsed into a
                             `datetime.datetime` object, such as a unix timestamp or
                             `numpy.datetime64`.
    :return: The parsed `datetime.datetime`
    """
    if not datetime_str:
        return None

    if isinstance(datetime_str, datetime):
        if datetime_str.tzinfo is None:
            return datetime_str.replace(tzinfo=timezone.utc)
        return datetime_str.astimezone(timezone.utc)

    if (isinstance(datetime_str, str) and datetime_str.isnumeric()) or isinstance(
        datetime_str, int
    ):
        n = int(datetime_str)
        dt_ms = datetime.fromtimestamp(n / 1000, tz=timezone.utc)
        if dt_ms > datetime(1970, 2, 1, tzinfo=timezone.utc):
            # assume it's a timestamp with milliseconds
            return dt_ms

        # it must not have milliseconds/microseconds, so return the time from the
        # timestamp as-is
        return datetime.fromtimestamp(n, tz=timezone.utc)

    if isinstance(datetime_str, float):
        return datetime.fromtimestamp(datetime_str, tz=timezone.utc)

    if isinstance(datetime_str, str):
        s = datetime_str.strip()

        # Allow ISO8601 with trailing Z by converting to an offset that fromisoformat understands
        # e.g. "2017-08-28T19:37:43.354Z" -> "2017-08-28T19:37:43.354+00:00"
        if s.endswith("Z"):
            s_iso = s[:-1] + "+00:00"
        else:
            s_iso = s

        # First try the modern parser (handles offsets like +00:00)
        try:
            dt = datetime.fromisoformat(s_iso)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass

        # Fall back to legacy format list (assume strings without offset are UTC)
        formats = [
            DATETIME_FMT_STR,
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]
        # Try multiple ways a datetime string could be formatted
        for fmt in formats:
            try:
                s_try = s
                if "." in s_try:
                    # "%f" supports up to 6 digits
                    dot = s_try.index(".")
                    # keep '.' + up to 6 digits
                    frac = s_try[dot + 1 :]
                    # stop at first non-digit (e.g., 'Z')
                    frac_digits = ""
                    for ch in frac:
                        if ch.isdigit():
                            frac_digits += ch
                        else:
                            break
                    if len(frac_digits) > 6:
                        s_try = (
                            s_try[: dot + 1 + 6] + s_try[dot + 1 + len(frac_digits) :]
                        )
                dt = datetime.strptime(s_try, fmt)
                # If the format didn't include timezone info, assume UTC and make aware
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                return dt
            except ValueError:
                continue
        raise ValueError(
            f"Date string '{datetime_str}' does not match any of the expected formats."
        )

    return None  # not parseable
