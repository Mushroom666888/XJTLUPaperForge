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

## Live-school boundary

The school site is currently closed, as reported by the user, and no valid saved browser login session was available. A new real-school download was **not** claimed or performed in this verification. Authentication, website availability and a real course export must be checked again when the site reopens. The synthetic tests are evidence for the local application and PDF pipeline, not evidence that the school's current pages or access rules work.
