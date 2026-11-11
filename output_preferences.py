"""Trusted native selection and atomic, per-user output preferences."""
import json
import os
from pathlib import Path, PureWindowsPath
import subprocess
import sys
import tempfile

from settings import DATA_ROOT, OUTPUT_ROOT, PROJECT_ROOT


def validate_directory(value, *, create=False):
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError('请选择有效的文件夹。')
    raw = str(value)
    if '\x00' in raw:
        raise ValueError('文件夹路径包含无效字符。')
    if os.name == 'nt':
        win = PureWindowsPath(raw)
        if not win.is_absolute() or raw.startswith(('\\\\.\\', '\\\\?\\')):
            raise ValueError('请选择完整的普通文件夹路径。')
        for part in win.parts[1:]:
            if any(c in part for c in '<>:"|?*') or part.endswith((' ', '.')) or PureWindowsPath(part).is_reserved():
                raise ValueError('文件夹路径包含 Windows 不支持的名称。')
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError('请选择完整的文件夹路径。')
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError('保存文件夹不存在，请重新选择。')
    path = path.resolve()
    # Probe the actual filesystem, rather than trusting permission bits on Windows.
    with tempfile.TemporaryFile(prefix='.paperforge-check-', dir=path) as probe:
        probe.write(b'PaperForge')
        probe.flush()
    return path


def course_directory(root, code):
    """Reject an existing junction/symlink that would redirect course output."""
    root = Path(root).resolve()
    target = root / code
    if target.resolve().parent != root:
        raise ValueError('课程文件夹指向了保存位置之外，请更换保存位置。')
    return target


def choose_directory(initial):
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'folder_picker.py'), str(initial)],
        capture_output=True, encoding='utf-8', errors='replace',
        env=dict(os.environ, PYTHONUTF8='1'), creationflags=flags,
    )
    if result.returncode:
        raise RuntimeError('系统文件夹选择器未能打开，请稍后重试。')
    try:
        return json.loads(result.stdout)['path']
    except (ValueError, KeyError) as exc:
        raise RuntimeError('文件夹选择器未返回有效结果。') from exc


class OutputPreferences:
    def __init__(self, file=None, default=None):
        self.file = Path(file) if file is not None else DATA_ROOT / 'preferences.json'
        self.default = Path(default) if default is not None else OUTPUT_ROOT
        self.path = self.default
        self.warning = ''
        try:
            saved = json.loads(self.file.read_text(encoding='utf-8'))
            value = saved['output_dir']
            if not isinstance(value, str) or not Path(value).is_absolute() or '\x00' in value:
                raise ValueError('Invalid saved path')
            self.path = Path(value)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError):
            self.warning = '保存位置设置无法读取，已恢复默认位置。'

    def save(self, value, *, create=False):
        path = validate_directory(value, create=create)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='preferences-', suffix='.tmp', dir=self.file.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump({'output_dir': str(path)}, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.file)
        finally:
            Path(name).unlink(missing_ok=True)
        self.path = path
        self.warning = ''
        return path
