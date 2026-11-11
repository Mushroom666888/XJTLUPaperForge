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
)
from pdf_output import normalize_course_code, validate_scale, save_paper_pdf
from task_events import check_cancelled, emit, TaskCancelled


@dataclass
class PaperLink:
    href: str
    text: str
    index: int
    page_num: int
    site_text: str = ""


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


def collect_all_papers(exam_tab, course_code=None):
    papers, seen_hrefs = [], set()
    page_num = 1
    while True:
        check_cancelled()
        found = collect_search_results(exam_tab)
        new_count = 0
        for item in found:
            if item["href"] not in seen_hrefs:
                seen_hrefs.add(item["href"])
                new_count += 1
                if course_code and not _matches_course(item.get("site_text", "") or item["text"], course_code):
                    continue
                papers.append(PaperLink(
                    href=item["href"], text=item["text"], index=item["index"],
                    page_num=page_num, site_text=item.get("site_text", ""),
                ))
        print(f"  搜索页 {page_num}: 读取 {new_count} 套，课程匹配累计 {len(papers)} 套")
        if page_num > 1 and not new_count:
            raise RuntimeError("翻页后没有新的搜索结果，已停止，避免重复循环。")
        if not has_next_page(exam_tab):
            return papers
        if not go_to_next_page(exam_tab):
            raise RuntimeError("无法进入下一页，搜索结果尚未收集完整，请重试。")
        page_num += 1


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


def extract_one_paper(context, exam_tab, paper, scale, course_code):
    owned_pages = []
    paper_name, output_file, page_count = "", "", 0
    try:
        check_cancelled()
        if paper.site_text and not _matches_course(paper.site_text, course_code):
            raise ValueError("搜索结果的课程编号不匹配，已拒绝导出。")
        detail = context.new_page()
        owned_pages.append(detail)
        detail.on("popup", lambda popup: owned_pages.append(popup))
        detail.set_viewport_size(VIEWPORT)
        detail.goto(paper.href, wait_until="domcontentloaded")
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
        if exam_type not in {"F", "R"}:
            raise ValueError("无法从网站或封面确认考试类型，未猜测为期末，未发布文件。")
        if year == "unknown":
            year = f"idx{paper.page_num:02d}_{paper.index:02d}"
        paper_name = f"{code}_{year}_{exam_type}"
        page_count = detect_total_pages(viewer)
        emit('paper', name=paper_name + '.pdf')
        emit('phase', phase='downloading')
        output_file = save_paper_pdf(viewer, course_code, paper_name, scale, page_count)
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
                papers = collect_all_papers(exam_tab, course_code)
                emit('catalog', total=len(papers))
                if not papers:
                    print(f"未找到 {course_code} 的试卷。")
                    return True
                print(f"共发现 {len(papers)} 套试卷，开始导出 PDF。")
                results = []
                for index, paper in enumerate(papers, 1):
                    check_cancelled()
                    emit('phase', phase='downloading')
                    emit('paper', name=f'试卷 {index} / {len(papers)}', retry=False)
                    print(f"\n[{index}/{len(papers)}] {paper.text}")
                    result = extract_one_paper(context, exam_tab, paper, scale, course_code)
                    if not result.success and "标记为封存" not in (result.error or ""):
                        check_cancelled()
                        emit('phase', phase='downloading')
                        emit('paper', name=result.paper_name + '.pdf' if result.paper_name else f'试卷 {index}', retry=True)
                        print(f"  首次未完成，重新尝试一次: {result.error}")
                        result = extract_one_paper(context, exam_tab, paper, scale, course_code)
                    results.append(result)
                    if result.success:
                        emit('verified', name=result.paper_name + '.pdf', pages=result.page_count)
                        print(f"  ✓ {result.paper_name}.pdf（{result.page_count} 页，已校验）")
                    else:
                        print(f"  ✗ {result.error}")
                failed = [result for result in results if not result.success]
                print(f"\n导出完成：共 {len(papers)} 套，成功 {len(papers)-len(failed)} 套，失败 {len(failed)} 套。")
                return not failed
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
        print(f"导出未完成: {exc}")
        sys.exit(1)
