"""Resource paths and executable dispatch shared by source and frozen builds."""
from pathlib import Path
from functools import lru_cache
import hashlib
import json
import sys

FROZEN = bool(getattr(sys, 'frozen', False))
RESOURCE_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)).resolve()
INSTALL_ROOT = Path(sys.executable).resolve().parent if FROZEN else RESOURCE_ROOT


def source_build_info(root=RESOURCE_ROOT):
    """Identify the exact runnable sources, including uncommitted/new modules."""
    from version import VERSION
    paths = list(root.glob('*.py'))
    for folder in ('frontend', 'skill'):
        paths.extend(path for path in (root/folder).rglob('*') if path.is_file()
                     and '__pycache__' not in path.parts and path.suffix.lower() in
                     {'.py', '.md', '.yaml', '.html', '.js', '.css', '.svg', '.png'})
    sources = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in sorted(paths)}
    digest = hashlib.sha256(json.dumps(sources, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return dict(version=VERSION, source_sha256=digest, source_files=sources)


@lru_cache(maxsize=1)
def build_info():
    if FROZEN:
        return json.loads((RESOURCE_ROOT/'build-info.json').read_text(encoding='utf-8'))
    return source_build_info()


def public_build_info():
    info = build_info()
    return {key: info[key] for key in ('version', 'source_sha256')}


def external_directory(value):
    path = Path(value).expanduser().resolve()
    roots = {RESOURCE_ROOT, INSTALL_ROOT}
    if FROZEN and INSTALL_ROOT.name == 'MacOS' and INSTALL_ROOT.parent.name == 'Contents':
        roots.add(INSTALL_ROOT.parent.parent)  # Protect the entire signed .app.
    for root in roots:
        if path == root or path.is_relative_to(root):
            raise ValueError('试卷和运行资料必须保存在程序目录之外，请选择其他文件夹。')
    return path


def script_command(script, *args):
    if FROZEN:
        executable = INSTALL_ROOT / ('paperforge-cli.exe' if sys.platform == 'win32' else 'paperforge')
        return [str(executable), '--worker', Path(script).stem, *map(str, args)]
    return [sys.executable, '-u', str(RESOURCE_ROOT / script), *map(str, args)]
