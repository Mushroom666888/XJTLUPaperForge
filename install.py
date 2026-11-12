"""Install this checkout and register its location with a local skill host."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

from platform_support import SUPPORTED_PLATFORMS

SKILL_NAME = 'xjtlu-paperforge'
PROJECT_ROOT = Path(__file__).resolve().parent


def python_path(root):
    return root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def install_skill(project, skills_dir):
    source = project / 'skill' / SKILL_NAME
    destination = skills_dir / SKILL_NAME
    files = [p for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts
             and p.suffix in ('.md', '.yaml', '.py')]
    if not (source / 'SKILL.md').is_file():
        raise FileNotFoundError('Bundled skill is missing.')
    for path in files:
        target = destination / path.relative_to(source)
        if not target.resolve().is_relative_to(destination.resolve()):
            raise ValueError('Skill destination contains an external link.')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    configuration = destination / 'installation.json'
    if configuration.is_symlink():
        raise ValueError('Installation configuration must be a regular file.')
    configuration.write_text(json.dumps({'project_root': str(project.resolve())}, indent=2), encoding='utf-8')
    return destination


def default_skills_dir(agent):
    if agent == 'claude':
        return Path.home() / '.claude' / 'skills'
    return Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'skills'


def main():
    parser = argparse.ArgumentParser(description='Install XJTLUPaperForge and its local skill.')
    parser.add_argument('--agent', choices=('codex','claude'), default='codex', help='Skill host (default: codex)')
    parser.add_argument('--skills-dir', type=Path, help='Explicit skill directory for any compatible local agent')
    parser.add_argument('--skills-only', action='store_true', help='Register an already assembled checkout without reinstalling dependencies')
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        raise SystemExit('Python 3.10 or newer is required; Python 3.12 is recommended.')
    if sys.platform not in SUPPORTED_PLATFORMS:
        raise SystemExit('This release targets Windows, macOS and desktop Linux.')
    if sys.platform != 'win32':
        print('macOS/Linux preview: school login and downloads still need verification on your desktop.', flush=True)
    interpreter = python_path(PROJECT_ROOT)
    if args.skills_only and not interpreter.is_file():
        raise SystemExit('Assemble the project first; --skills-only requires an existing .venv.')
    if not interpreter.is_file():
        print('[1/3] Creating a private Python environment...', flush=True)
        venv.EnvBuilder(with_pip=True).create(PROJECT_ROOT / '.venv')
    if not args.skills_only:
        print('[2/3] Installing dependencies...', flush=True)
        subprocess.run([str(interpreter), '-m', 'pip', 'install', '-r', str(PROJECT_ROOT / 'requirements.txt')], check=True)
        subprocess.run([str(interpreter), '-m', 'pip', 'check'], check=True)
    skills_dir = (args.skills_dir or default_skills_dir(args.agent)).expanduser().resolve()
    installed = install_skill(PROJECT_ROOT, skills_dir)
    print('[3/3] Registered the xjtlu-paperforge skill.', flush=True)
    print(f'Program: {PROJECT_ROOT}\nSkill: {installed}')
    invocation = '/xjtlu-paperforge' if args.agent == 'claude' else '$xjtlu-paperforge'
    print(f'In your local agent, use {invocation} to open the paper app.')
    print(f'Or run directly: "{interpreter}" "{PROJECT_ROOT / "app.py"}" --open')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f'Installation failed: {exc}')
