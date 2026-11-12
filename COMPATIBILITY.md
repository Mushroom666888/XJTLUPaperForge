# Compatibility validation

Windows with Chrome and Edge has been checked against the real school site on 2026-11-12, after the site reopened. Other agent clients and operating systems retain the explicit limits below; successful browser testing does not establish support for every host.

## Agent / model compatibility

PaperForge is a local Python app. Its skill consists of `SKILL.md`, optional host metadata and a standard-library Python launcher; it has no Codex API dependency and makes no LLM API calls. The model name alone does not determine compatibility. A host must be able to read the skill, run local commands, keep the local server running and open a local browser.

| Host | Current evidence | Boundary |
| --- | --- | --- |
| Codex local | Installed skill launcher and actual app health verified | School session still required |
| Claude Code local | Official Skill format matches; Claude-directory installation and the installed Python launcher start a real server from an unrelated working directory | Claude Code client is not installed here; native slash-command discovery was not executed |
| DeepSeek / Doubao in a local agent with Skill + terminal support | Same portable launcher can be called; custom skill directory supported | No named DeepSeek/Doubao host is installed here; model branding does not prove a local execution capability |
| Pure browser chat / cloud sandbox | Can read instructions but cannot thereby access the user's Windows files, local Chrome or local server | A local execution bridge would be needed; not provided or claimed |

Claude Code's documented `~/.claude/skills/<name>/SKILL.md` layout and `/skill-name` invocation were checked against the [official documentation](https://code.claude.com/docs/en/skills.md). The optional `agents/openai.yaml` file only supplies Codex UI metadata; the executable launcher is independent of it.

```powershell
# Default: assemble and register with Codex
py -3.12 install.py
# Register with Claude Code
py -3.12 install.py --agent claude
# Already assembled: register without reinstalling dependencies
.\.venv\Scripts\python.exe install.py --agent claude --skills-only
# Another compatible host: use that host's actual Skill directory
py -3.12 install.py --skills-dir "C:\path\to\your\agent\skills"
# Any local agent can run the bundled launcher directly
py -3.12 skill/xjtlu-paperforge/scripts/launch.py
```

Do not copy another machine's `.venv`, login profile or `installation.json`. Install from the downloaded checkout so its actual location is registered.

## Browser compatibility

The **workbench browser** displays a local HTML page. The **school browser** is a separate dedicated browser controlled through Chromium's CDP interface. They need not be the same program.

- Chrome is always preferred when detected. Fallback controls are hidden in that case.
- Only when Chrome is absent does the workbench offer installed Edge, Brave or Chromium. It requires an explicit selection, persists that selection, and returns to Chrome automatically if Chrome later becomes available.
- Fallback selection passes a browser ID, never an arbitrary executable supplied by a webpage. Choices cannot change during an active task.
- Each browser has its own profile and session file. A Chrome school session is never imported into Edge.
- **Real Edge validation:** the existing capture/quality tests run in installed Edge. A complete browser form → local API → child Python process → real Edge → verified 300-DPI PDF → custom directory flow was executed against synthetic school pages. Chrome absence was simulated; Edge, subprocesses, files and PDF validation were real.
- **Live-school validation (2026-11-12):** the user logged in separately in Chrome and Edge. The real workbench, API, subprocess, school search and export pipeline produced six PDFs / 61 pages in each browser: Chrome at 300 DPI, Edge at 192 DPI. Each run used its own temporary destination outside the repository. Only Chrome absence was injected to expose Edge's fallback control; school pages, authentication and document processing were not mocked. See [VERIFICATION.md](VERIFICATION.md).
- Edge's launcher can exit before its browser child is ready. Startup now waits for the actual CDP endpoint; session recording obtains the browser PID, and owned temporary browsers are closed explicitly to avoid orphan children.
- Brave/Chromium detection is implemented, but those browsers are not installed on this host and their full workflows are not claimed tested.
- Firefox/Safari cannot replace the current Chromium CDP school-reading engine. The standard local workbench may render in them, but that was not tested here.

## Operating systems

**The supported application remains Windows 10/11.** No macOS/Linux support claim is added.

This host has no macOS environment, and WSL reports that Linux support is not installed. Browser discovery has unit coverage for macOS application locations and Linux commands, but that does not establish a working application on those systems. The installer deliberately continues to reject unsupported platforms.

Concrete remaining porting work includes `os.startfile` folder opening, Windows `ctypes.windll`/`taskkill` process management, platform-specific data locations, GUI/Tk packaging and actual school SSO/PDF rendering on each target. These are engineering tasks, not an inherent model limitation. No OS installation or system-setting changes were performed to simulate proof.

## Reproducible verification

```powershell
.\.venv\Scripts\python.exe doctor.py --json
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

`doctor.py` is read-only and reports Python, supported OS, dependencies, detected browsers and skill bundle presence. It explicitly reports school login/export as untested. Automated tests cover Chrome priority, explicit fallback, invalid IDs, persistence, profile isolation, multiple agent installation locations, real launcher health, actual Edge rendering/capture and the synthetic full-stack flow. Skipping a missing browser is reported as a skip, never a pass for that browser.

Final local verification on Windows with Python 3.12.10: **104 tests passed**, including Chrome and installed Edge; `pip check`, Skill frontmatter validation and Git whitespace checks passed. The running workbench was restarted through the installed Skill launcher, then checked in real Chrome: default Chrome selected, fallback controls hidden, `D:\XJTLUPaperForge-Output` restored, no page JavaScript errors. A running task keeps its chosen browser even if Chrome becomes available before it finishes.

macOS/Linux and uninstalled agent/browser clients remain separate unverified targets. A school-site redesign, authentication change or browser update may require renewed live validation; the automated suite uses synthetic pages and never downloads school papers in CI.
