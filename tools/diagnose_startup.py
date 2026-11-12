"""CI-only diagnostics for disposable local server/browser startup; no school data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_config import detect_browsers


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        env = dict(os.environ, XJTLUPAPERFORGE_DATA=str(root/'runtime'), PYTHONUTF8='1')
        probe = '''import faulthandler, time
faulthandler.dump_traceback_later(5)
t=time.monotonic()
import app
print('app import seconds:', time.monotonic()-t, flush=True)
s=app.Server()
print('server ready seconds:', time.monotonic()-t, flush=True)
s.server_close()
faulthandler.cancel_dump_traceback_later()
'''
        try:
            result = subprocess.run([sys.executable, '-u', '-c', probe], env=env, capture_output=True, text=True, timeout=20)
            print(result.stdout, result.stderr, flush=True)
        except subprocess.TimeoutExpired as exc:
            print('Server probe timed out:', exc.stdout, exc.stderr, flush=True)
        for browser, executable in detect_browsers().items():
            command = [executable, '--headless=new', '--no-first-run', '--no-default-browser-check',
                       '--proxy-server=direct://', '--proxy-bypass-list=*',
                       f'--user-data-dir={root/browser}', '--dump-dom', 'about:blank']
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=20)
                print(browser, 'exit:', result.returncode, 'stderr:', result.stderr[-6000:], flush=True)
            except subprocess.TimeoutExpired as exc:
                print(browser, 'probe timed out:', exc.stderr, flush=True)


if __name__ == '__main__':
    main()
