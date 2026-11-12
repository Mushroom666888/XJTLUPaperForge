# XJTLUPaperForge

This is a local application for the XJTLU past-paper website. Windows 10/11 has live-school verification; macOS and desktop Linux are preview ports whose school login and exports still require native desktop acceptance. Keep the user's downloaded papers and browser state outside the source checkout.

For a request to install or assemble this downloaded repository, read README.md and run `py -3.12 install.py` from this directory (or another available Python 3.10+). The installer creates `.venv`, installs dependencies and registers the `xjtlu-paperforge` Codex skill with this checkout's actual path. `--agent claude` or `--skills-dir` registers with another local Skill host; see COMPATIBILITY.md for verified boundaries. Do not hardcode a drive, username or original developer path. Prefer Google Chrome; only when it is absent may the user explicitly select another detected Chromium browser. Do not import another user's browser profile.

For a request to open the application, run the installed skill's `scripts/launch.py` with Python. It starts the app and verifies its local health before reporting success. The browser interface handles course selection, manual school login, export progress and results. No school login or paper download is needed for installation checks.

On macOS/Linux, assemble with `python3 install.py` and use `.venv/bin/python` in place of `.venv\Scripts\python.exe`. Manual school login needs a graphical desktop. Folder picking uses AppleScript on macOS, Zenity/KDialog or Tkinter on Linux. Do not claim that headless CI proves school SSO, native dialog UX or every distribution/CPU architecture. This source distribution requires Python; a chat-only agent cannot install or run it without local execution capabilities.

For code changes, use `.venv\Scripts\python.exe -m unittest discover -s tests -v` and `.venv\Scripts\python.exe -m pip check` (with the POSIX interpreter path above on macOS/Linux). Tests use generated documents and mocked school pages. Keep actual PDFs, screenshots of papers, `.env`, cookies, browser profiles, run logs and machine-specific `installation.json` out of the repository. Retain the upstream MIT license.
