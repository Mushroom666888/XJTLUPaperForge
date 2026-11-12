# Frontend verification

The workbench is served directly by Python; there is no TypeScript/npm build or ESLint configuration. All UI assets are local.

## Automated checks

Run from the checkout using its virtual environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

The redesign was checked on Windows with installed Google Chrome: 72 tests passed, dependency consistency passed, and Git whitespace validation passed. After the user's change to seven expressions, the 16 application/API/browser tests were repeated and passed. No original tests were removed or weakened.

The first GitHub runner exposed Windows short-name aliases in its temporary directory (`RUNNER~1` versus the canonical profile name). Fixtures now normalize their temporary roots before comparing them to the application's resolved output paths; the full destination and file-preservation assertions remain intact. CI uses UTF-8 for readable Chinese diagnostics.

Coverage includes course normalization/deduplication, empty/invalid input, both quality modes, authenticating/searching/downloading/validating UI states, full and partial success, failure, zero results, cooperative cancellation/retry, reduced motion, keyboard radio/focus behavior, and 320–1440px layout widths. Browser tests assert no page JavaScript exceptions.

Directory tests cover the default, native-picker selection and cancellation (injected returns in automation), real write probes, permission errors, invalid Windows names, missing directories, persistent preferences, atomic-save failures, junction escape rejection, frozen job paths, concurrent selection/start rejection, child process environment propagation, and opening the current versus last-job directory.

PDF integration tests use a **synthetic PDF.js-style viewer** but perform real page capture, lossless PDF construction, per-page/pixel/order/DPI verification, same-volume staging and final publication. A custom destination on the project drive was tested with 300 DPI and capture scratch on the system drive. The tests check that no temporary PNG/PDF files remain, existing files are protected, cancellation does not publish a partial file, and unrelated browser tabs survive.

## Actual desktop checks

- Ran the local app and captured desktop and narrow layouts plus waiting, downloading, validation, partial, cancelled, success and reduced-motion states. Task-state captures are visibly labelled synthetic. `tools/capture_review.py` reproduces them under ignored `.impeccable/review/`.
- Operated the real Windows native folder chooser: selected a dedicated test directory and observed its path returned by the backend; cancellation returned `None`. A visible, updated Tk owner keeps the native modal discoverable and in front of the browser.
- Used the installed skill launcher to restart the idle app and verified its actual local health endpoint. No active export was interrupted.
- Impeccable detector ran once. Small functional text findings were fixed; cream was retained because it is explicitly requested. Independent rendered review was performed; the user subsequently excluded the two-hanging-leg expression, leaving seven source-derived stickers.

## Live-school verification — 2026-11-12

After the school site reopened, the user manually authenticated in separate Chrome and Edge profiles. Both runs used the actual workbench controls, local API, Python worker, school search and PDF viewer, with separate temporary output folders outside the source checkout.

| Browser | Output quality | Result |
| --- | --- | --- |
| Chrome | 300 DPI | Six PDFs, 61 pages; complete |
| Edge | 192 DPI | Six PDFs, 61 pages; complete |

The real course search returned six papers. Every file was checked for the reader's expected page count, readable PDF structure, per-page pixel hashes, order, duplicate/blank pages and effective resolution. The final files were checked again independently of the task result. Poppler rendered the first and last page of every PDF for visual review, plus detailed cover/body samples; margins, page numbers, diagrams and source watermarks were preserved. Both workbenches displayed complete status without JavaScript errors, and no PNG or staging directories remained in the course folders.

Chrome is installed on this machine, so only its absence from browser discovery was simulated in the isolated Edge workbench to exercise the fallback selection. Edge itself, the school login, all school responses and all resulting PDFs were real. No Chrome session was imported into Edge. This proves the tested Windows/browser flows; it does not establish macOS/Linux or uninstalled agent-client compatibility.

Temporary real-paper downloads, renders and the one-off acceptance driver are removed after review. No real papers, personal file inventory, cookies or browser profiles are committed. The maintained automated tests continue to use synthetic documents.

After audit fixes, both complete flows were repeated from empty temporary destinations: Chrome again produced six PDFs / 61 pages at a measured minimum 300 DPI, and Edge six / 61 at 192 DPI, with zero frontend JavaScript errors. Independent pixel/page/order/DPI checks passed; all 122 page drawing layouts and first/last-page renders were reviewed. A transient reader timeout in an intermediate diagnostic recovered on the subsequent full run; timeouts remain bounded failures. Closing the test browser during a status poll also exposed an expected connection-abort traceback; the HTTP response boundary now handles that disconnect without changing task state or hiding worker failures.

The full local regression suite passed all **103 tests** after the audit fixes. After the final browser-disconnect handling change, all **16 application/API/frontend tests** were repeated and passed; the browser-ownership guard was also checked again against both real browser sessions. Installer execution, dependency consistency, Skill validation and workflow syntax checks passed. CI now runs the actual installer into an isolated Skill directory before testing with the project's `.venv`, matching the launcher and installation tests' real runtime requirements.

## First-principles and adversarial review

[AUDIT.md](AUDIT.md) records the project-wide invariants, reproduced failures and corrections. Added cases cover exact course suffixes, ambiguous exam types, archive-name collisions, concurrent startup and crash recovery, shutdown races, stale browser identity, bounded stalled requests, cancellation during validation and corrupted local records. Authentication tests distinguish a partly rendered or hidden-template homepage from a visible authenticated state, accept automatic SSO restoration, and ensure URL query/fragment secrets stay out of login diagnostics.

PDF fault injection preserved every embedded image and its pixel manifest while independently removing page drawing commands, moving an image off the page, cropping the page and changing rotation. All four originally passed the pixel-only check; the strengthened validator rejects them and refuses to reuse the files. The generated format still passes the normal export tests without reducing its quality checks or adding dependencies.

## Explicit school-login reminder

The workbench now displays “请去登录哦” only when a worker requests manual authentication, names that task's actual browser, and says that work resumes automatically after login. The account label and disabled start button show the waiting state as well. A browser regression verifies the real event-to-API-to-DOM transition, removal after authentication completes, and a 320px layout.

An additional live check launched a fresh, isolated Chrome profile, opened the real school's password form through the normal login worker, and verified the reminder in the actual workbench at desktop and narrow widths. Cancellation cleared the reminder. No credentials were entered, no papers were downloaded, and the existing authenticated browser sessions were preserved. The temporary browser, runtime and profile were cleaned up after the check.

After the login-reminder addition, the complete local suite passed **104 tests** in 120.308 seconds; dependency and Git whitespace checks passed again.
