"""Small desktop OS adapters; PDF/search logic stays platform-independent."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys


SUPPORTED_PLATFORMS = ('win32', 'darwin', 'linux')


def default_data_root():
    user_home = Path.home()
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', str(user_home/'AppData/Local'))) / 'XJTLUPaperForge'
    if sys.platform == 'darwin':
        return user_home/'Library/Application Support/XJTLUPaperForge'
    if sys.platform == 'linux':
        configured = Path(os.environ.get('XDG_DATA_HOME', ''))
        base = configured if configured.is_absolute() else user_home/'.local/share'
        return base/'XJTLUPaperForge'
    raise RuntimeError('当前系统尚未适配。请使用 Windows、macOS 或桌面 Linux。')


def desktop_available():
    return sys.platform != 'linux' or bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))


def require_desktop():
    if not desktop_available():
        raise RuntimeError('需要 Linux 图形桌面会话才能打开学校登录窗口或文件夹；纯 SSH/无桌面环境无法完成手动登录。')


def picker_backend():
    if sys.platform == 'darwin':
        return 'osascript' if shutil.which('osascript') else None
    if sys.platform == 'linux':
        for name in ('zenity', 'kdialog'):
            if shutil.which(name):
                return name
    return 'tkinter' if importlib.util.find_spec('tkinter') else None


def open_directory(value):
    folder = Path(value).resolve()
    if not folder.is_dir():
        raise ValueError('保存文件夹不存在，请重新选择。')
    require_desktop()
    if sys.platform == 'win32':
        os.startfile(str(folder))
        return
    command = 'open' if sys.platform == 'darwin' else 'xdg-open'
    executable = shutil.which(command)
    if not executable:
        raise RuntimeError(f'系统缺少文件夹打开工具 {command}。请在文件管理器中打开保存位置。')
    try:
        subprocess.run([executable, str(folder)], check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError('文件管理器未能打开，请检查图形桌面是否可用。') from exc
