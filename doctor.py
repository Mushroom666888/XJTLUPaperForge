"""Report local capabilities without logging in or downloading school papers."""
import argparse
import importlib.util
import json
import os
import platform
import sys

from browser_config import BrowserPreferences, detect_browsers
from output_preferences import OutputPreferences
from settings import DATA_ROOT, PROJECT_ROOT
from platform_support import SUPPORTED_PLATFORMS, desktop_available, picker_backend


def report():
    available = detect_browsers()
    browser = BrowserPreferences(DATA_ROOT).info()
    modules = ('playwright','PIL','dotenv','pypdf','img2pdf','rapidocr','onnxruntime')
    missing = [name for name in modules if importlib.util.find_spec(name) is None]
    checks = [
        {'name':'python', 'ok':sys.version_info >= (3,10), 'detail':platform.python_version()},
        {'name':'platform', 'ok':sys.platform in SUPPORTED_PLATFORMS, 'detail':platform.system() + (' verified on a local desktop' if sys.platform == 'win32' else ' preview; live-school validation pending')},
        {'name':'dependencies', 'ok':not missing, 'detail':missing or 'available'},
        {'name':'desktop', 'ok':desktop_available(), 'detail':'Graphical desktop required for manual school login'},
        {'name':'folder_picker', 'ok':bool(picker_backend()), 'detail':picker_backend() or 'Install Zenity/KDialog or a Python distribution with Tkinter'},
        {'name':'browser', 'ok':bool(browser['selected']), 'detail':browser},
        {'name':'skill_bundle', 'ok':(PROJECT_ROOT/'skill/xjtlu-paperforge/SKILL.md').is_file(), 'detail':'Agent Skills markdown + Python launcher'},
    ]
    return {'ready_for_local_launch':all(check['ok'] for check in checks), 'checks':checks,
            'detected_browsers':list(available), 'output_dir':str(OutputPreferences().path),
            'school_login_checked':False, 'school_export_checked':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    result = report()
    if args.json:
        print(json.dumps(result,ensure_ascii=False,indent=2))
    else:
        for check in result['checks']:
            print(('OK' if check['ok'] else 'CHECK') + ' ' + check['name'] + ': ' + str(check['detail']))
        print('School login and downloads were not tested.')
    return 0 if result['ready_for_local_launch'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
