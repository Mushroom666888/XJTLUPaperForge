"""Publish a complete file atomically without replacing an existing destination."""
import ctypes
import errno
import os
from pathlib import Path
import sys
import tempfile


def publish_no_replace(source, destination):
    source, destination = Path(source), Path(destination)
    if sys.platform == 'win32':
        os.rename(source, destination)  # Windows MoveFile refuses an existing name.
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin' and hasattr(libc, 'renamex_np'):
        function = libc.renamex_np
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        args = (os.fsencode(source), os.fsencode(destination), 4)  # RENAME_EXCL
    elif sys.platform == 'linux' and hasattr(libc, 'renameat2'):
        function = libc.renameat2
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        args = (-100, os.fsencode(source), -100, os.fsencode(destination), 1)  # RENAME_NOREPLACE
    else:
        function = None
    if function is not None:
        function.restype = ctypes.c_int
        if function(*args) == 0:
            return
        error = ctypes.get_errno()
        if error not in (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP):
            raise OSError(error, os.strerror(error), str(destination))
    # Old kernels may lack the rename primitive. Hard links remain a safe fallback;
    # the preflight detects filesystems supporting neither before capture starts.
    os.link(source, destination)
    source.unlink()


def check_publication_directory(directory):
    """Probe both publication and refusal to overwrite on the actual filesystem."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.paperforge-check-', dir=directory) as temporary:
        source, target = Path(temporary)/'new', Path(temporary)/'existing'
        source.write_bytes(b'new'); target.write_bytes(b'keep')
        try:
            publish_no_replace(source, target)
        except FileExistsError:
            pass
        else:
            raise RuntimeError('保存位置不支持禁止覆盖的文件发布，请更换文件系统。')
        if target.read_bytes() != b'keep' or source.read_bytes() != b'new':
            raise RuntimeError('保存位置不能安全保留已有文件，请更换文件夹。')
        target.unlink()
        try:
            publish_no_replace(source, target)
        except OSError as exc:
            raise RuntimeError('保存位置不支持安全发布完整文件，请更换文件系统。') from exc
