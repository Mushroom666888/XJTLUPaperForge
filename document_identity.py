"""Bind reuse to a school record and, when available, its complete PDF bytes."""
import hashlib
import re
from task_events import check_cancelled


def document_identity(viewer, href, course, year, exam_type, timeout_ms=10000):
    check_cancelled()
    digest = viewer.evaluate('''async timeoutMs => {
        let timer;
        try {
            return await Promise.race([
                (async () => {
                    const doc = window.PDFViewerApplication?.pdfDocument;
                    if (!doc?.getData || !globalThis.crypto?.subtle) return null;
                    const bytes = await doc.getData();
                    if (!bytes?.byteLength) return null;
                    const hash = await crypto.subtle.digest('SHA-256', bytes);
                    return [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, '0')).join('');
                })().catch(() => null),
                new Promise(resolve => { timer=setTimeout(() => resolve(null), timeoutMs); })
            ]);
        } finally { clearTimeout(timer); }
    }''', timeout_ms)
    check_cancelled()
    # Never store signed URLs, authentication tickets or query parameters in a PDF.
    identity = {'version': 1, 'record_sha256': hashlib.sha256(href.encode('utf-8')).hexdigest(),
                'course': course, 'year': year, 'exam_type': exam_type}
    if isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest):
        identity['content_sha256'] = digest
    # Without source bytes the caller must recapture and compare every page to reuse.
    return identity
