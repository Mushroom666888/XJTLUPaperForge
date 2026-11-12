"""Run a native folder dialog on its own main thread, outside HTTP workers."""
import json
from pathlib import Path
import subprocess
import sys
from platform_support import picker_backend, require_desktop


MAC_PICKER_SCRIPT = '''on run argv
    try
        set chosen to choose folder with prompt "PaperForge · 选择试卷保存位置" default location (POSIX file (item 1 of argv))
        return POSIX path of chosen
    on error number -128
        return ""
    end try
end run'''


def native_choice(initial, backend):
    if backend == 'osascript':
        command = ['osascript', '-e', MAC_PICKER_SCRIPT, str(initial)]
    elif backend == 'zenity':
        command = ['zenity', '--file-selection', '--directory', '--title=PaperForge · 保存位置',
                   '--filename=' + str(initial) + '/']
    elif backend == 'kdialog':
        command = ['kdialog', '--getexistingdirectory', str(initial), '--title', 'PaperForge · 保存位置']
    else:
        raise ValueError('Unknown folder picker backend.')
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
    except OSError as exc:
        raise RuntimeError('系统文件夹选择器不可用，请检查桌面组件是否已安装。') from exc
    if result.returncode == 1 and backend in ('zenity', 'kdialog'):
        return None
    if result.returncode:
        raise RuntimeError('系统文件夹选择器未能打开，请检查图形桌面是否可用。')
    # Strip the output protocol's newline, not whitespace belonging to the path.
    return result.stdout.rstrip('\r\n') or None


def main():
    require_desktop()
    initial = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home()
    while not initial.is_dir() and initial != initial.parent:
        initial = initial.parent
    backend = picker_backend()
    if backend is None:
        raise RuntimeError('缺少系统文件夹选择器。请安装 Zenity/KDialog 或带 Tkinter 的 Python。')
    if backend != 'tkinter':
        print(json.dumps({'path': native_choice(initial, backend)}, ensure_ascii=False), flush=True)
        return
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise RuntimeError('当前 Python 的 Tkinter 不可用，请安装桌面组件后重试。') from exc
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError('无法打开文件夹选择器，请检查 Tkinter 和图形桌面是否可用。') from exc
    root.title('PaperForge · 保存位置')
    root.geometry('360x110')
    root.resizable(False, False)
    root.configure(background='#f5f3e9')
    tk.Label(root, text='请在系统对话框中选择试卷保存位置。',
             background='#f5f3e9', foreground='#234c3c', pady=30).pack()
    root.attributes('-topmost', True)
    # An updated, visible owner keeps the native modal in front of the browser.
    root.update()
    root.lift()
    try:
        folder = filedialog.askdirectory(parent=root, title='PaperForge · 选择试卷保存位置',
                                         initialdir=str(initial), mustexist=True)
        print(json.dumps({'path': folder or None}, ensure_ascii=False), flush=True)
    finally:
        root.destroy()


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as exc:
        print('PAPERFORGE_PICKER_ERROR:' + str(exc), file=sys.stderr)
        raise SystemExit(1)
