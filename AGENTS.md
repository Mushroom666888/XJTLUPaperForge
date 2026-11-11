# XJTLUPaperForge

This is a Windows 10/11 local application for the XJTLU past-paper website. Keep the user's downloaded papers and browser state outside the source checkout.

For a request to install or assemble this downloaded repository, read README.md and run `py -3.12 install.py` from this directory (or another available Python 3.10+). The installer creates `.venv`, installs dependencies and registers the `xjtlu-paperforge` Codex skill with this checkout's actual path. `--agent claude` or `--skills-dir` registers with another local Skill host; see COMPATIBILITY.md for verified boundaries. Do not hardcode a drive, username or original developer path. Prefer Google Chrome; only when it is absent may the user explicitly select another detected Chromium browser. Do not import another user's browser profile.

For a request to open the application, run the installed skill's `scripts/launch.py` with Python. It starts the app and verifies its local health before reporting success. The browser interface handles course selection, manual school login, export progress and results. No school login or paper download is needed for installation checks.

For code changes, use `.venv\Scripts\python.exe -m unittest discover -s tests -v` and `.venv\Scripts\python.exe -m pip check`. Tests use generated documents and mocked school pages. Keep actual PDFs, screenshots of papers, `.env`, cookies, browser profiles, run logs and machine-specific `installation.json` out of the repository. Retain the upstream MIT license.
