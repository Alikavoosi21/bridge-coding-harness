"""Close the in-process gap between idle checking and launching a task.

Durable worker/workspace leases still own effects. This short, nonblocking
entry lock prevents a human edit and a launch from both passing idle first.
"""
from contextlib import contextmanager
from functools import wraps
from threading import Lock

from server.errors import ApiError

_entry=Lock()


@contextmanager
def exclusive_entry():
    if not _entry.acquire(blocking=False):
        raise ApiError('workspace_busy','Another task launch or human edit is in progress.',status_code=409)
    try:yield
    finally:_entry.release()


def serialize_entry(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        with exclusive_entry():return function(*args,**kwargs)
    return wrapped
