"""Chrome-first browser discovery; fallback choice is explicit and local."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

NAMES = {'chrome': 'Google Chrome', 'edge': 'Microsoft Edge', 'brave': 'Brave', 'chromium': 'Chromium'}


def detect_browsers():
    candidates = {key: [] for key in NAMES}
    for key, commands in {'chrome': ('chrome', 'google-chrome', 'google-chrome-stable'),
                          'edge': ('msedge', 'microsoft-edge', 'microsoft-edge-stable'),
                          'brave': ('brave', 'brave-browser'),
                          'chromium': ('chromium', 'chromium-browser')}.items():
        candidates[key].extend(shutil.which(command) for command in commands)
    if sys.platform == 'win32':
        for base in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
            folder = os.environ.get(base)
            if not folder:
                continue
            candidates['chrome'].append(str(Path(folder)/'Google/Chrome/Application/chrome.exe'))
            candidates['edge'].append(str(Path(folder)/'Microsoft/Edge/Application/msedge.exe'))
            candidates['brave'].append(str(Path(folder)/'BraveSoftware/Brave-Browser/Application/brave.exe'))
            candidates['chromium'].append(str(Path(folder)/'Chromium/Application/chrome.exe'))
    elif sys.platform == 'darwin':
        for root in (Path('/Applications'), Path.home()/'Applications'):
            for key, app, binary in [('chrome','Google Chrome','Google Chrome'), ('edge','Microsoft Edge','Microsoft Edge'),
                                     ('brave','Brave Browser','Brave Browser'), ('chromium','Chromium','Chromium')]:
                candidates[key].append(str(root/f'{app}.app/Contents/MacOS'/binary))
    return {key: str(Path(path).resolve()) for key, paths in candidates.items()
            for path in [next((path for path in paths if path and Path(path).is_file()), None)] if path}


def saved_fallback(data_root):
    try:
        key = json.loads((Path(data_root)/'browser.json').read_text(encoding='utf-8'))['browser']
        return key if key in NAMES else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def preferred_browser(data_root, available=None):
    available = detect_browsers() if available is None else available
    if 'chrome' in available:
        return 'chrome'
    fallback = saved_fallback(data_root)
    return fallback if fallback in available else None


class BrowserPreferences:
    def __init__(self, data_root, detector=None):
        self.root = Path(data_root)
        self.detector = detector or detect_browsers

    def info(self):
        available = self.detector()
        selected = preferred_browser(self.root, available)
        return {'chrome_available': 'chrome' in available, 'selected': selected,
                'name': NAMES.get(selected, ''),
                'choices': [{'id': key, 'name': NAMES[key]} for key in available if key != 'chrome']}

    def select(self, key):
        available = self.detector()
        if 'chrome' in available:
            raise ValueError('已检测到 Chrome，将优先使用 Chrome。')
        if not isinstance(key, str) or key not in available or key not in NAMES:
            raise ValueError('请选择已安装的受支持浏览器。')
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='browser-', suffix='.tmp', dir=self.root)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump({'browser': key}, stream)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, self.root/'browser.json')
        finally:
            Path(temporary).unlink(missing_ok=True)

    def require(self):
        info = self.info()
        if not info['selected']:
            raise ValueError('未检测到 Chrome。请先选择其他已安装的浏览器，或安装 Chrome 后刷新。')
        return info['selected']
