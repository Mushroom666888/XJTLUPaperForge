"""Keep XJTLUPaperForge's PDFs and browser state outside the source directory."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / '.env')


def _path_setting(name, default):
    value = os.environ.get(name, '').strip()
    path = Path(value).expanduser() if value else default
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


OUTPUT_ROOT = _path_setting('XJTLUPAPERFORGE_OUTPUT', PROJECT_ROOT.parent / 'XJTLUPaperForge-Output')
DATA_ROOT = _path_setting(
    'XJTLUPAPERFORGE_DATA',
    Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'XJTLUPaperForge',
)
WORK_ROOT = DATA_ROOT / 'work' / 'captures'
PROFILE_DIR = DATA_ROOT / 'chrome_profile'
SESSION_FILE = DATA_ROOT / '.browser_session.json'
