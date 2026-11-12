"""Keep XJTLUPaperForge's PDFs and browser state outside the source directory."""

import os
from pathlib import Path

from dotenv import load_dotenv
from browser_config import preferred_browser, NAMES
from platform_support import default_data_root

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
    default_data_root(),
)
WORK_ROOT = DATA_ROOT / 'work' / 'captures'
BROWSER_KIND = os.environ.get('XJTLUPAPERFORGE_BROWSER') or preferred_browser(DATA_ROOT) or 'chrome'
if BROWSER_KIND not in NAMES:
    raise ValueError('Unsupported XJTLUPAPERFORGE_BROWSER value.')
PROFILE_DIR = DATA_ROOT / f'{BROWSER_KIND}_profile'
SESSION_FILE = DATA_ROOT / ('.browser_session.json' if BROWSER_KIND == 'chrome' else f'.browser_session-{BROWSER_KIND}.json')
