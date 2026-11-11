"""Run a native folder dialog on its own main thread, outside HTTP workers."""
import json
from pathlib import Path
import sys


def main():
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
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
        initial = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home()
        while not initial.is_dir() and initial != initial.parent:
            initial = initial.parent
        folder = filedialog.askdirectory(parent=root, title='PaperForge · 选择试卷保存位置',
                                         initialdir=str(initial), mustexist=True)
        print(json.dumps({'path': folder or None}, ensure_ascii=False), flush=True)
    finally:
        root.destroy()


if __name__ == '__main__':
    main()
