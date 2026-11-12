"""Search a course and export verified PDFs into exam_pages/<course>/ only."""

import argparse
from dataclasses import dataclass
import re
import sys
import time
from typing import Optional

from playwright.sync_api import sync_playwright

from browser_session import open_chrome
from capture_canvas import (
    VIEWPORT, SPECIAL_PROFILE, login, navigate_to_past_exam_papers,
    agree_and_search, collect_search_results, resolve_paper_metadata,
    read_detail_text, detect_total_pages, has_next_page, go_to_next_page,
    read_search_total,
)
from pdf_output import normalize_course_code, validate_scale, save_paper_pdf
from task_events import check_cancelled, emit, TaskCancelled
from document_identity import document_identity
from result_audit import catalog_items, record_id, verified_fields, consume_result, audit_files, finalize_result


@dataclass
class PaperLink:
    href: str
    text: str
    index: int
    page_num: int
    site_text: str = ""
    rejection: Optional[str] = None


@dataclass
class ExtractionResult:
    paper: PaperLink
    paper_name: str
    output_file: str
    page_count: int
    success: bool
    error: Optional[str] = None


def _matches_course(text, course_code):
    return bool(re.search(r"(?<![A-Z0-9])" + re.escape(course_code.upper()) + r"(?![A-Z0-9])", text.upper()))


def collect_all_papers(exam_tab, course_code=None, *, report=emit):
    papers, seen_hrefs = [], set()
    page_num = 1
    expected = read_search_total(exam_tab)
    if expected is None:
        raise RuntimeError('无法确认学校网站的试卷总数，不能判定清单完整。请检查搜索页后重试。')
    report('inventory', total=expected)
    duplicates = False
    while True:
        check_cancelled()
        found = collect_search_results(exam_tab)
        new_count = 0
        for item in found:
            if item['href'] in seen_hrefs:
                duplicates = True
            if item["href"] not in seen_hrefs:
                seen_hrefs.add(item["href"])
                new_count += 1
                rejection = None
                if course_code and not _matches_course(item.get("site_text", "") or item["text"], course_code):
                    rejection = '搜索结果课程编号不匹配或无法确认，已拒绝导出。'
                papers.append(PaperLink(
                    href=item["href"], text=item["text"], index=item["index"],
                    page_num=page_num, site_text=item.get("site_text", ""),
                    rejection=rejection,
                ))
        print(f"  搜索页 {page_num}: 读取 {new_count} 套，清单累计 {len(papers)}/{expected} 套")
        if page_num > 1 and not new_count:
            raise RuntimeError("翻页后没有新的搜索结果，已停止，避免重复循环。")
        current_total = read_search_total(exam_tab)
        if current_total != expected:
            raise RuntimeError(f'搜索期间学校总数发生变化（{expected} → {current_total}），请重新搜索。')
        if len(papers) > expected:
            raise RuntimeError(f'试卷清单超出学校总数：{len(papers)}/{expected}，请重新搜索。')
        if not has_next_page(exam_tab):
            if len(papers) != expected:
                raise RuntimeError(f'试卷清单不完整：学校显示 {expected} 份，实际收集 {len(papers)} 份；缺失或重复的条目尚未核清，未宣布完成。')
            if duplicates:
                raise RuntimeError('试卷清单包含重复条目，不能静默合并后宣布完整。')
            return papers
        if not go_to_next_page(exam_tab):
            raise RuntimeError("无法进入下一页，搜索结果尚未收集完整，请重试。")
        page_num += 1
        current_total = read_search_total(exam_tab)
        if current_total != expected:
            raise RuntimeError(f'搜索期间学校总数发生变化（{expected} → {current_total}），请重新搜索。')


def _wait_for_pdf_viewer(detail_page, owned_pages, timeout=60):
    """Only consider the detail page and popups opened by that page."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        check_cancelled()
        for candidate in reversed(owned_pages):
            if candidate.is_closed():
                continue
            try:
                ready = candidate.evaluate("""() => Boolean(
                    window.PDFViewerApplication?.pdfDocument &&
                    window.PDFViewerApplication?.pdfViewer?.getPageView
                )""")
                if ready:
                    return candidate
            except Exception:
                pass  # The popup may still be navigating.
        if detail_page.is_closed():
            raise RuntimeError("试卷详情页被关闭。")
        detail_page.wait_for_timeout(100)
    raise RuntimeError(f"PDF 阅读器未在 {timeout} 秒内加载完成，请检查学校网站后重试。")


def extract_one_paper(context, exam_tab, paper, scale, course_code, paper_names=None):
    owned_pages = []
    paper_name, output_file, page_count = "", "", 0
    try:
        check_cancelled()
        if paper.rejection:
            raise ValueError(paper.rejection)
        if paper.site_text and not _matches_course(paper.site_text, course_code):
            raise ValueError("搜索结果的课程编号不匹配，已拒绝导出。")
        detail = context.new_page()
        owned_pages.append(detail)
        detail.on("popup", lambda popup: owned_pages.append(popup))
        detail.set_viewport_size(VIEWPORT)
        detail.goto(paper.href, wait_until="domcontentloaded")
        check_cancelled()
        view_button = detail.get_by_text("View Online", exact=True)
        embargo = detail.get_by_text(re.compile(r"Access to this file is embargoed until", re.I))
        view_button.or_(embargo).first.wait_for(state="visible", timeout=15000)
        if embargo.count():
            raise RuntimeError(f"网站将试卷标记为封存，未提供在线阅读入口：{embargo.first.inner_text()}")
        detail_text = read_detail_text(detail)
        view_button.click()
        viewer = _wait_for_pdf_viewer(detail, owned_pages)
        viewer.set_viewport_size(VIEWPORT)

        code, year, exam_type = resolve_paper_metadata(
            paper.text, paper.site_text, detail_text, viewer, course_code,
        )
        if code != course_code:
            raise ValueError("试卷课程编号与请求不一致，未发布文件。")
        if exam_type not in {"F", "R"}:
            raise ValueError("无法从网站或封面确认考试类型，未猜测为期末，未发布文件。")
        if year == "unknown":
            year = f"idx{paper.page_num:02d}_{paper.index:02d}"
        paper_name = f"{code}_{year}_{exam_type}"
        if paper_names is not None:
            previous = paper_names.get(paper_name)
            if previous is not None and previous != paper.href:
                raise ValueError("不同试卷的归档名称冲突，未将旧文件当作另一份试卷复用。")
            paper_names[paper_name] = paper.href
        page_count = detect_total_pages(viewer)
        emit('paper', name=paper_name + '.pdf')
        emit('phase', phase='downloading')
        identity = document_identity(viewer, paper.href, code, year, exam_type)
        output_file = save_paper_pdf(viewer, course_code, paper_name, scale, page_count,
                                     source_identity=identity)
        return ExtractionResult(paper, paper_name, output_file, page_count, True)
    except TaskCancelled:
        raise
    except Exception as exc:
        return ExtractionResult(paper, paper_name, output_file, 0, False, str(exc))
    finally:
        for page in reversed(owned_pages):
            try:
                if not page.is_closed():
                    page.close()
            except Exception:
                pass


def batch_capture(course_code, scale=2.0, headless=False):
    course_code = normalize_course_code(course_code)
    validate_scale(scale)
    from settings import OUTPUT_ROOT
    row = dict(course=course_code, expected=None, papers=[], errors=[], status='working', message='')
    def report(kind, **fields):
        consume_result(row, dict(event=kind, **fields))
        emit(kind, **fields)

    with sync_playwright() as playwright:
        with open_chrome(playwright, headless=headless, user_data_dir=SPECIAL_PROFILE) as (context, persistent):
            context.set_default_timeout(30000)
            index_page = context.new_page() if persistent else (
                context.pages[0] if context.pages else context.new_page()
            )
            index_page.set_viewport_size(VIEWPORT)
            exam_tab = None
            try:
                login(index_page, allow_manual=persistent or not headless)
                check_cancelled()
                emit('phase', phase='searching')
                exam_tab = navigate_to_past_exam_papers(index_page)
                agree_and_search(exam_tab, course_code)
                papers = collect_all_papers(exam_tab, course_code, report=report)
                report('catalog', total=len(papers), items=catalog_items(papers))
                if not papers:
                    report('summary',total=0,succeeded=[],failed=[])
                    finalize_result(row, 0, {}, str)
                    if row['errors']:
                        raise RuntimeError('；'.join(row['errors']))
                    print(f"未找到 {course_code} 的试卷。")
                    return True
                print(f"共发现 {len(papers)} 套试卷，开始导出 PDF。")
                results, paper_names = [], {}
                for index, paper in enumerate(papers, 1):
                    check_cancelled()
                    emit('phase', phase='downloading')
                    emit('paper', name=f'试卷 {index} / {len(papers)}', retry=False)
                    print(f"\n[{index}/{len(papers)}] {paper.text}")
                    result = extract_one_paper(context, exam_tab, paper, scale, course_code, paper_names)
                    if not result.success and not paper.rejection and not any(reason in (result.error or "") for reason in ("标记为封存", "名称冲突", "课程编号与请求不一致")):
                        check_cancelled()
                        emit('phase', phase='downloading')
                        emit('paper', name=result.paper_name + '.pdf' if result.paper_name else f'试卷 {index}', retry=True)
                        print(f"  首次未完成，重新尝试一次: {result.error}")
                        result = extract_one_paper(context, exam_tab, paper, scale, course_code, paper_names)
                    results.append(result)
                    if result.success:
                        report('verified', **verified_fields(result))
                        print(f"  ✓ {result.paper_name}.pdf（{result.page_count} 页，已校验）")
                    else:
                        report('paper_failed', id=record_id(paper.href), label=paper.site_text or paper.text,
                             error=result.error)
                        print(f"  ✗ {result.error}")
                failed = [result for result in results if not result.success]
                report('summary',total=len(papers),
                     succeeded=[record_id(r.paper.href) for r in results if r.success],
                     failed=[record_id(r.paper.href) for r in failed])
                finalize_result(row, 0, audit_files(row, OUTPUT_ROOT, scale, check_cancelled), str)
                if row['status'] != 'complete':
                    for reason in row['errors']:
                        emit('fatal', error=reason)
                        print(f'导出未完成: {reason}')
                    print(row['message'])
                    return False
                print(f"\n导出完成：{len(row['papers'])}/{row['expected']} 份已通过清单与磁盘复核。")
                return True
            finally:
                if persistent:
                    for page in (exam_tab, index_page):
                        try:
                            if page is not None and not page.is_closed():
                                page.close()
                        except Exception:
                            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="按课程导出历年试卷，只保存校验通过的 PDF")
    parser.add_argument("course_code", nargs="?", help="课程代码，例如 CAN209")
    parser.add_argument("--scale", type=float, default=2.0,
                        help="缩放倍数，默认 2.0（约 192 DPI）；3.125 约为 300 DPI")
    parser.add_argument("--headless", action="store_true", help="无界面运行，不适合首次登录")
    args = parser.parse_args()
    code = args.course_code or input("请输入课程代码: ").strip()
    if not code:
        sys.exit(0)
    try:
        sys.exit(0 if batch_capture(code, args.scale, args.headless) else 1)
    except TaskCancelled:
        print('任务已取消，已校验的 PDF 已保留。')
        sys.exit(2)
    except Exception as exc:
        emit('fatal',error=str(exc))
        print(f"导出未完成: {exc}")
        sys.exit(1)
