"""Small, credential-free event protocol shared by the CLI and local workbench."""
import json
import os
from pathlib import Path

PREFIX = '@paperforge '


class TaskCancelled(Exception):
    pass


def check_cancelled():
    marker = os.environ.get('XJTLUPAPERFORGE_CANCEL_FILE')
    if marker and Path(marker).exists():
        raise TaskCancelled('任务已取消，已校验的 PDF 已保留。')


def emit(event, **values):
    if os.environ.get('XJTLUPAPERFORGE_EVENTS') == '1':
        print(PREFIX + json.dumps(dict(event=event, **values), ensure_ascii=False), flush=True)
