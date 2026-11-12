"""Exercise a relocated package with empty Python configuration and restricted PATH."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.request import Request,urlopen
import psutil


@contextmanager
def reap_test_processes(root):
    """Check teardown before deleting an isolated bundle; touch only this copy."""
    try:
        yield
    finally:
        owned = []
        for process in psutil.process_iter(['exe']):
            try:
                if process.info['exe'] and Path(process.info['exe']).resolve().is_relative_to(root.resolve()):
                    owned.append(process)
            except (OSError, psutil.Error): pass
        _, alive = psutil.wait_procs(owned, timeout=10)
        if alive:
            for process in alive:
                try: process.terminate()
                except psutil.Error: pass
            _, remaining = psutil.wait_procs(alive, timeout=3)
            for process in remaining:
                try: process.kill()
                except psutil.Error: pass
            psutil.wait_procs(remaining, timeout=3)
            raise RuntimeError('Package left a test process alive after shutdown; reaped before cleanup.')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('bundle',type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='paperforge-clean-') as temporary, reap_test_processes(Path(temporary)):
        root=Path(temporary).resolve();copy=root/'relocated app 中文'/args.bundle.name
        shutil.copytree(args.bundle.resolve(),copy,symlinks=True)
        executable=copy/('paperforge-cli.exe' if os.name=='nt' else 'Contents/MacOS/paperforge' if copy.suffix=='.app' else 'paperforge')
        env=dict(os.environ)
        for key in list(env):
            if key.startswith(('PYTHON','XJTLUPAPERFORGE','VIRTUAL_ENV','CONDA')):env.pop(key)
        env.update(PYTHONNOUSERSITE='1',PYTHONPATH='',PYTHONHOME='',
                   XJTLUPAPERFORGE_DATA=str(root/'data'),XJTLUPAPERFORGE_OUTPUT=str(root/'papers'))
        # Windows system tools only. POSIX needs /usr/bin for desktop/browser helpers;
        # the executable still embeds CPython and is never launched through python.
        env['PATH']=str(Path(os.environ['SystemRoot'])/'System32') if os.name=='nt' else '/usr/bin:/bin'
        def run(*args,timeout=180):
            completed=subprocess.run([str(executable),*args],cwd=root,env=env,capture_output=True,
                                     text=True,encoding='utf-8',errors='replace',timeout=timeout)
            if completed.returncode:raise RuntimeError(completed.stdout+'\n'+completed.stderr)
            return completed.stdout
        print(run('--version'))
        print(run('--self-test'))
        skills=root/'agent skills'
        print(run('--register-skill','codex','--skills-dir',str(skills)))
        record=json.loads((skills/'xjtlu-paperforge/installation.json').read_text(encoding='utf-8'))
        assert Path(record['launcher'])==executable
        if os.name == 'nt':
            # Exercise the same windowed executable that a double-click starts.
            subprocess.run([str(copy/'PaperForge.exe'),'--no-browser'],cwd=root,env=env,check=True,timeout=40)
            first=None
        else:
            first=run('--no-browser',timeout=40)
        state=json.loads((root/'data/ui.json').read_text(encoding='utf-8'));url=f'http://127.0.0.1:{state["port"]}'
        try:
            second=run('--no-browser',timeout=40)
            assert (first is None or url in first) and url in second
            with urlopen(url,timeout=5) as response:html=response.read().decode('utf-8-sig')
            token=re.search(r'name="paperforge-token" content="([^"]+)"',html)[1]
            request=Request(url+'/api/shutdown',data=b'{}',headers={'X-PaperForge-Token':token})
            urlopen(request,timeout=5).close()
            deadline=time.monotonic()+10
            while (root/'data/ui.json').exists() and time.monotonic()<deadline:time.sleep(.1)
            assert not (root/'data/ui.json').exists()
            # State is removed immediately before process teardown/log-handle release.
            for _ in range(50):
                try:
                    (root/'data/logs/app-startup.log').unlink();break
                except PermissionError:time.sleep(.1)
        finally:
            if (root/'data/ui.json').exists():
                raise RuntimeError('Package process still running; inspect isolated test runtime.')
    print('PASS: relocated bundle, isolated Python environment, real OCR/browser export, skill, health, duplicate launch and shutdown')


if __name__=='__main__':main()
