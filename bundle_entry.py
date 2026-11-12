"""Self-contained desktop launcher and explicit subprocess entry points."""
import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time
from runtime_paths import RESOURCE_ROOT, INSTALL_ROOT, script_command

# Frozen applications do not honor every interpreter environment setting.
# Keep parent/worker output and Chinese paths consistent on Windows consoles.
for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8', errors='replace')

WORKERS = ('app', 'login', 'batch_capture', 'capture_canvas', 'folder_picker', 'doctor',
           'synthetic_worker')


def launch(open_browser=True):
    from settings import DATA_ROOT
    from app import existing_url
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    state = DATA_ROOT/'ui.json'
    if url := existing_url(state):
        if open_browser:
            from browser_config import open_workbench
            open_workbench(url, DATA_ROOT)
        print(json.dumps({'ready':True,'url':url},ensure_ascii=False),flush=True)
        return 0
    command = script_command('app.py', *(['--open'] if open_browser else []))
    log = DATA_ROOT/'logs/app-startup.log';log.parent.mkdir(parents=True,exist_ok=True)
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP |
             subprocess.CREATE_NO_WINDOW) if os.name == 'nt' else 0
    with log.open('a',encoding='utf-8') as stream:
        process=subprocess.Popen(command,cwd=INSTALL_ROOT,stdin=subprocess.DEVNULL,
            stdout=stream,stderr=stream,creationflags=flags,start_new_session=os.name!='nt')
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        if url:=existing_url(state):
            print(json.dumps({'ready':True,'url':url},ensure_ascii=False),flush=True)
            return 0
        if process.poll() not in (None,0):break
        time.sleep(.2)
    if process.poll() is None:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
    raise RuntimeError(f'工作台未能就绪。请查看 {log}')


def main():
    if len(sys.argv)>1 and sys.argv[1]=='--worker':
        if len(sys.argv)<3 or sys.argv[2] not in WORKERS:
            raise ValueError('Unknown worker.')
        module=sys.argv[2];sys.argv=[module,*sys.argv[3:]]
        runpy.run_module(module,run_name='__main__')
        return 0
    parser=argparse.ArgumentParser(description='XJTLUPaperForge bundled desktop app')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--self-test',action='store_true',help='Run local synthetic export and OCR checks; no school traffic')
    parser.add_argument('--register-skill',choices=('codex','claude'))
    parser.add_argument('--skills-dir',type=Path)
    parser.add_argument('--version',action='store_true')
    args=parser.parse_args()
    if args.version:
        from version import VERSION
        print(VERSION);return 0
    if args.self_test:
        from packaged_smoke import main as check
        return check()
    if args.register_skill:
        from install import install_skill,default_skills_dir
        executable=script_command('app.py')[0]
        result=install_skill(RESOURCE_ROOT,(args.skills_dir or default_skills_dir(args.register_skill)).expanduser().resolve(),launcher=executable)
        print(str(result));return 0
    return launch(not args.no_browser)


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        if sys.stdout is None and sys.platform=='win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,str(exc),'PaperForge 启动失败',0x10)
        else:
            print(str(exc),file=sys.stderr)
        raise SystemExit(1)
