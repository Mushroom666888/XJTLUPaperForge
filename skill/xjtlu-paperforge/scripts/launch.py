"""Locate the installed checkout, then start its local app without a console."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen


def find_project(skill_root):
    candidates = []
    if configured := os.environ.get('XJTLUPAPERFORGE_HOME'):
        candidates.append(Path(configured).expanduser())
    configuration = skill_root / 'installation.json'
    try:
        candidates.append(Path(json.loads(configuration.read_text(encoding='utf-8'))['project_root']))
    except (OSError, ValueError, KeyError, TypeError):
        pass  # A valid explicit override or bundled checkout can still recover.
    candidates.append(skill_root.parent.parent)
    for candidate in candidates:
        if (candidate / 'app.py').is_file() and (candidate / 'settings.py').is_file():
            return candidate.resolve()
    raise RuntimeError('Program not found. Run install.py in the downloaded XJTLUPaperForge folder again.')


def main():
    parser = argparse.ArgumentParser(description='Open XJTLUPaperForge')
    parser.add_argument('--no-browser', action='store_true', help='Start the local server without opening a window')
    parser.add_argument('--print-root', action='store_true', help='Print the resolved installation directory')
    args = parser.parse_args()
    skill_root = Path(__file__).resolve().parent.parent
    launcher = None
    try:
        record = json.loads((skill_root/'installation.json').read_text(encoding='utf-8'))
        launcher = Path(record['launcher'])
    except (OSError, ValueError, KeyError, TypeError):
        pass  # Source installations and relocated bundles can be registered again.
    if launcher is not None and launcher.is_file() and not os.environ.get('XJTLUPAPERFORGE_HOME'):
        if args.print_root:
            print(launcher.parent)
            return
        subprocess.run([str(launcher), *(['--no-browser'] if args.no_browser else [])],
            check=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        return
    root = find_project(skill_root)
    if args.print_root:
        print(root)
        return
    python = root / '.venv' / ('Scripts/pythonw.exe' if os.name == 'nt' else 'bin/python')
    if not python.is_file():
        raise RuntimeError('Python environment missing. Run install.py in the program folder.')
    console_python = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    configured_data = subprocess.check_output(
        [str(console_python), '-c', 'import json,settings; from runtime_paths import public_build_info; print(json.dumps(dict(data=str(settings.DATA_ROOT),build=public_build_info())))'],
        cwd=root, encoding='utf-8', env=dict(os.environ, PYTHONUTF8='1'),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    ).strip()
    configuration = json.loads(configured_data)
    runtime = Path(configuration['data'])
    (runtime / 'logs').mkdir(parents=True, exist_ok=True)
    command = [str(python), str(root / 'app.py')]
    if not args.no_browser:
        command.append('--open')
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == 'nt' else 0
    with (runtime / 'logs/app-startup.log').open('a', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=log, creationflags=flags, start_new_session=os.name != 'nt')
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        try:
            state = json.loads((runtime / 'ui.json').read_text(encoding='utf-8'))
            if not isinstance(state, dict):
                raise ValueError('Invalid workbench state')
            port = int(state['port'])
            if state.get('project_root') == str(root) and 1 <= port <= 65535:
                url = f'http://127.0.0.1:{port}'
                with urlopen(url + '/health', timeout=1) as response:
                    health = json.load(response)
                if isinstance(health, dict) and health.get('app') == 'XJTLUPaperForge' and health.get('instance') == state.get('instance'):
                    if any(health.get(key) != value for key, value in configuration['build'].items()):
                        raise RuntimeError('该位置仍运行着其他版本的工作台，请先在旧工作台点击“退出应用”，再启动当前版本。')
                    print(f'XJTLUPaperForge is ready: {url}')
                    return
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if process.poll() not in (None, 0):
            break
        time.sleep(0.2)
    raise RuntimeError(f'The app did not become ready. See {runtime / "logs/app-startup.log"}')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        raise SystemExit(str(exc))
