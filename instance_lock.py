"""Hold one workbench per runtime directory, including simultaneous launches."""
from contextlib import contextmanager
import errno
import os


@contextmanager
def workbench_lock(path):
    with open(path, 'a+b') as stream:
        # Windows permits locking a range beyond EOF. Writing an initial byte
        # would itself race with a second process that has already locked it.
        stream.seek(0)
        acquired = False
        try:
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
            yield acquired
        finally:
            if acquired:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
