# Project review: first principles and adversarial checks

Reviewed the supported Windows application, launcher/installer, browser lifecycle, school search and metadata selection, PDF pipeline, local HTTP API, frontend state handling, persistence, tests and CI. The legacy capture script is not a product entrypoint. No adversarial traffic was sent to the school; fault cases use local fixtures and disposable processes.

## First-principles pass

| Required outcome | Implementation and evidence |
| --- | --- |
| Export the requested course | Exact course filtering, metadata checks and refusal to borrow another course's PDF metadata, including letter suffixes. Search errors and zero results are distinct from complete exports. |
| Keep authentication with the user | Manual school SSO in dedicated browser profiles; no credential collection in the workbench. Chrome and Edge have separate sessions. |
| Publish complete, readable PDFs | Real reader page counts, finished canvases at the selected scale, consecutive page capture, blank/duplicate checks, decoded pixel hashes, order and effective-DPI validation. Live Chrome and Edge runs each produced six PDFs / 61 pages; independent checks and Poppler visual review followed. |
| Write to the actual selected location | Native folder selection, real write probes, atomic preferences, a frozen task destination and containment checks. Final publication is staged on the destination volume and does not overwrite an existing file. The lower-level merge utility retains its explicit legacy recapture behavior; the product only calls it on a new staging file. |
| Report only actual work | Completion requires successful workers and matching verified file counts. Unknown totals stay unknown; partial, empty, failed and cancelled states do not become success. UI strings use text nodes, not injected HTML. |
| Keep concurrent operations consistent | One workbench per runtime directory, locked task/picker/browser changes, and an atomic shutdown gate. Cancellation reaches page capture and PDF verification. |
| Remain installable and honest about support | The launcher resolves the actual checkout and tests health, CI uses the project's installed virtual environment, and compatibility documentation distinguishes real browser evidence from untested agent/OS combinations. |

## Adversarial pass and fixes

| Scenario | Finding and correction |
| --- | --- |
| Request MTH102 while metadata contains MTH102TC | Reproduced prefix-based acceptance. Metadata now requires exact course equality, and PDF fallback rejects a different course before borrowing its year/type. |
| A cover contains both Final and Resit | Ambiguous cover text now remains unknown rather than defaulting to either exam type. |
| Image pixels survive but the PDF page no longer displays them correctly | Reproduced acceptance of empty/shifted drawing streams and cropped/rotated pages. Validation now checks the exporter's full-page image drawing commands, transform, page boxes and rotation in addition to decoded pixels. Damaged existing files are not reused. |
| Different catalog entries resolve to one archive name | A shared per-run registry rejects the collision and preserves the first file. It does not report the existing file as a successful export of a second paper. |
| Start two workbenches simultaneously | Reproduced two independent servers. A process-level file lock now serializes startup. The test also terminates the owning process and verifies that a new workbench can recover. The race/recovery scenario passed 12 consecutive runs. |
| Submit new work while shutdown is being accepted | Shutdown now reserves the idle state under the same task lock; subsequent jobs, folder selection and browser changes are rejected. |
| Saved session contains a stale PID or malformed identifiers | Session fields are validated before probing a port. Both attaching and closing verify the connected browser's actual PID before operating on tabs. Closing sends CDP Browser.close; it no longer kills a process based only on a cached PID. Real Chrome and Edge checks confirm that the mismatched-PID case leaves the browser usable. |
| PDF text promises never resolve or a search response body stalls | Metadata reads have a bounded Promise race. Search readiness uses a bounded network-idle wait instead of an unbounded response-body wait. Both cases are tested with real browsers and local fixtures. |
| Cancel while checking a large PDF | Verification checks cancellation between pages; cancellation is not swallowed by the existing-file check. No partial PDF is published. |
| Corrupted UI/installation records | Invalid UI state can be replaced, and an explicit valid project override can recover from a broken installation record. |
| Public homepage partially renders before Login appears | Authentication now requires a visible positive Logout marker. Missing Login controls alone cannot establish authentication. A browser regression also rejects a hidden Logout template. |
| School SSO restores a session without showing a password form | Login accepts the authenticated homepage as a successful SSO outcome and does not force another manual login. Diagnostic URLs remove both query strings and fragments, which can contain authentication codes. |

Existing tests also exercise wrong Host/Origin and missing API tokens, invalid courses and quality values, arbitrary-path payloads, junction escape, non-writable folders, interrupted preference saves, low-resolution/corrupt PDFs, unchanged original files after failure, repeated pagination, partial results, and unrelated browser tabs remaining open.

## Validation and limits

See [VERIFICATION.md](VERIFICATION.md) for the final suite and live-school results. The new regression cases remain in the project so these failures cannot silently return; temporary real-paper samples, screenshots, one-off drivers and test installations are removed after acceptance.

This review establishes the tested behavior and records the corrected failure cases. It does not turn an untested OS/browser/agent client into a supported one, or guarantee future school-site changes. Current compatibility boundaries are maintained in [COMPATIBILITY.md](COMPATIBILITY.md).
