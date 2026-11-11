"""XJTLUPaperForge：读取已登录 PDF.js 阅读器中完整绘制的页面，生成经校验的 PDF。

提供两个入口：
  capture_canvas(scale)       — 单篇提取（向后兼容）
  batch_capture.py            — 批量提取该科目所有试卷
"""

import re
import os
import sys
import base64
import time
from functools import lru_cache
from urllib.parse import urlsplit

# 修复 Windows GBK 终端编码问题
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from task_events import check_cancelled, emit
from playwright.sync_api import sync_playwright
from browser_session import open_chrome
from settings import PROFILE_DIR

VIEWPORT = {"width": 2560, "height": 1440}
BASE_URL = "https://etd.xjtlu.edu.cn/index.html#/index"
# 独立浏览器资料保存在应用数据目录；首次使用由用户手动登录。
SPECIAL_PROFILE = str(PROFILE_DIR)
RESIT_PATTERN = re.compile(r'\bRE[- ]?SIT\b|补考|\bSUPPLEMENTARY\b', re.IGNORECASE)
FINAL_PATTERN = re.compile(r'\bFINAL\b', re.IGNORECASE)
# ═══════════════════════════════════════════════════════════════
# 元数据解析
# ═══════════════════════════════════════════════════════════════

def parse_exam_metadata(page):
    """从首页文字提取元数据；无可用文字时识别首页画布。"""
    layer_text = page.evaluate("""() => {
        const layer = document.querySelector('.textLayer');
        return layer ? (layer.textContent || '') : '';
    }""") or ""
    pdf_text = page.evaluate("""async () => {
        const deadline = Date.now() + 10000;
        while (Date.now() < deadline) {
            const pdf = window.PDFViewerApplication?.pdfDocument;
            if (pdf) {
                try {
                    const firstPage = await pdf.getPage(1);
                    const content = await firstPage.getTextContent();
                    return content.items.map(item => item.str || '').join(' ');
                } catch (error) {
                    return '';
                }
            }
            await new Promise(resolve => setTimeout(resolve, 200));
        }
        return '';
    }""") or ""
    text = f"{layer_text} {pdf_text}"
    metadata = parse_metadata_from_text(text)
    if metadata[0] != "UNKNOWN" and metadata[1] != "unknown" and (
        RESIT_PATTERN.search(text) or FINAL_PATTERN.search(text)
    ):
        return metadata

    result = _capture_rendered_page(page, 1, 2.0)
    if not result.get("ok"):
        raise RuntimeError(f"封面尚未完整绘制: {result.get('reason', 'unknown')}")
    encoded = result["dataURL"].split(",", 1)[1]
    try:
        ocr_text = _ocr_image_text(base64.b64decode(encoded))
    except Exception as exc:
        raise RuntimeError(f"无法识别封面信息: {exc}") from exc
    combined = f"{text} {ocr_text}"
    code, year, exam_type = parse_metadata_from_text(combined)
    if not (RESIT_PATTERN.search(combined) or FINAL_PATTERN.search(combined)):
        exam_type = "unknown"
    return code, year, exam_type


@lru_cache(maxsize=1)
def _ocr_engine():
    from rapidocr import RapidOCR
    return RapidOCR()


def _ocr_image_text(image_bytes):
    result = _ocr_engine()(image_bytes)
    return " ".join(result.txts or ())


def parse_metadata_from_text(text):
    """从任意文本中提取课程代码、年份、考试类型（降级备用）"""
    code, year, exam_type = "UNKNOWN", "unknown", "F"

    m = re.search(r'\b([A-Z]{3})\s*(\d{3}[A-Z]{0,2})\b', text)
    if m:
        code = m.group(1) + m.group(2)

    year_pattern = re.compile(
        r'(?<!\d)(?P<start>(?:19|20)\d{2}|\d{2})\s*[-/]\s*'
        r'(?P<end>(?:19|20)\d{2}|\d{2})(?!\d)'
    )
    for match in year_pattern.finditer(text):
        start_text, end_text = match.group("start", "end")
        start_year = int(start_text) if len(start_text) == 4 else 2000 + int(start_text)
        next_year = start_year + 1
        end_matches = (
            int(end_text) == next_year
            if len(end_text) == 4
            else int(end_text) == next_year % 100
        )
        if end_matches:
            year = f"{start_year}-{next_year % 100:02d}"
            break

    if RESIT_PATTERN.search(text):
        exam_type = "R"
    elif FINAL_PATTERN.search(text):
        exam_type = "F"

    return code, year, exam_type


def resolve_paper_metadata(link_text, row_text, detail_text, pdf_viewer, course_code):
    """优先使用网站的试卷信息，PDF 仅补全网站缺失的字段。"""
    code, year, exam_type = "UNKNOWN", "unknown", None
    for source in (row_text, link_text, detail_text):
        if not source:
            continue
        source = source.upper()
        source_code, source_year, source_type = parse_metadata_from_text(source)
        if source_code != "UNKNOWN" and not source_code.startswith(course_code.upper()):
            continue
        if code == "UNKNOWN" and source_code != "UNKNOWN":
            code = source_code
        if year == "unknown" and source_year != "unknown":
            year = source_year
        has_resit = bool(RESIT_PATTERN.search(source))
        has_final = bool(FINAL_PATTERN.search(source))
        if exam_type is None and has_resit != has_final:
            exam_type = source_type
        if code != "UNKNOWN" and year != "unknown" and exam_type is not None:
            break

    if code == "UNKNOWN" or year == "unknown" or exam_type is None:
        pdf_code, pdf_year, pdf_type = parse_exam_metadata(pdf_viewer)
        if code == "UNKNOWN":
            code = pdf_code
        if year == "unknown":
            year = pdf_year
        if exam_type is None:
            exam_type = pdf_type

    return (course_code if code == "UNKNOWN" else code,
            year, "unknown" if exam_type is None else exam_type)


def read_detail_text(page):
    """读取试卷详情区域文字，供命名使用。"""
    return page.evaluate("""() => {
        const content = document.querySelector('main, .el-main, article, .detail')
            || document.body;
        return (content?.innerText || '').trim().substring(0, 12000);
    }""")


# ═══════════════════════════════════════════════════════════════
# 可复用流程函数
# ═══════════════════════════════════════════════════════════════

def _is_logged_in(page):
    """可靠的登录态检测。

    未登录首页本身就渲染 'Past Exam Papers'，因此不能单用它判断。
    已登录标志：页面在 etd 域名、已渲染出 Past Exam Papers、
    且不存在未登录才有的 'User Login' / 'Login' 按钮。
    """
    try:
        if urlsplit(page.url).hostname != "etd.xjtlu.edu.cn":
            return False
        if not page.get_by_text("Past Exam Papers", exact=True).count():
            return False
        if page.get_by_text("User Login", exact=True).count():
            return False
        if page.get_by_role("button", name="Login").count():
            return False
        return True
    except Exception:
        return False


def login(page, username=None, password=None, allow_manual=True):
    """打开考试系统，复用会话或等待用户手动登录（不自动提交凭证）。

    XJTLU SSO 带深信服 UEBA 风控（鼠标轨迹指纹），自动点击的零轨迹行为
    会被风控 400 拦截，因此登录一律由用户手动完成。
    """
    check_cancelled()
    emit("phase", phase="login")
    print("打开首页...")
    page.goto(BASE_URL, wait_until="domcontentloaded")
    # 等 SPA 渲染完成
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(1500)

    if _is_logged_in(page):
        print("已复用浏览器登录状态。")
        return

    # 未登录：首页不会自动跳 SSO，需要主动点击 Login 按钮
    print("未检测到登录态，点击 Login 按钮跳转 SSO...")
    try:
        page.get_by_role("button", name="Login").click()
    except Exception:
        try:
            page.click("text=Login")
        except Exception as e:
            print(f"点击 Login 按钮失败: {type(e).__name__}: {str(e)[:100]}")

    # 跳转链：etd → trust.xjtlu.edu.cn (深信服 SDP) → sso → uim 登录页
    print("等待 SSO 跳转到登录页...")
    try:
        page.wait_for_selector("input[type='password']", timeout=20000)
        print("已到达登录页，请在浏览器窗口中手动完成登录。")
    except Exception:
        safe_url = urlsplit(page.url)._replace(query="").geturl()
        print(f"警告：20 秒内未出现登录表单，当前页面: {safe_url[:120]}")

    if not allow_manual:
        raise RuntimeError(
            "浏览器登录状态已失效。请先去掉 --headless 运行一次并手动登录。"
        )

    emit("phase", phase="waiting")
    print("程序将等待登录完成（最多 5 分钟）...")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        check_cancelled()
        try:
            if _is_logged_in(page):
                print("登录成功，继续流程。")
                return
            page.wait_for_timeout(1000)
        except Exception as e:
            print(f"等待登录时浏览器异常：{type(e).__name__}: {str(e)[:120]}")
            print("提示：登录窗口被关闭或 Chrome 崩溃，请重新运行脚本。")
            raise RuntimeError("登录窗口已关闭") from e

    raise RuntimeError("等待手动登录超时，请重新运行程序。")


def navigate_to_past_exam_papers(page):
    """点击 Past Exam Papers，返回新标签页。原 page 保留不动。"""
    print("点击 Past Exam Papers...")
    opened = []
    def remember_popup(popup):
        opened.append(popup)
    page.on("popup", remember_popup)
    try:
        page.click("text=Past Exam Papers")
        page.wait_for_timeout(1000)
        exam_tab = opened[-1] if opened else page
    finally:
        page.remove_listener("popup", remember_popup)

    exam_tab.set_viewport_size(VIEWPORT)
    exam_tab.wait_for_load_state("domcontentloaded")
    exam_tab.wait_for_timeout(1000)
    return exam_tab


def agree_and_search(page, course_code):
    """等待搜索表单和服务器响应，避免慢加载被误判成零结果。"""
    if "/Policy/" in page.url:
        print("等待并点击 Agree 按钮...")
        agree = page.get_by_text("Agree", exact=True)
        agree.wait_for(state="visible", timeout=30000)
        agree.click()

    search_input = page.locator(
        'input[type="text"]:not([readonly]):not([disabled]):visible'
    ).first
    search_input.wait_for(state="visible", timeout=30000)
    page.wait_for_load_state("networkidle", timeout=30000)
    search_input.fill(course_code)
    search_input.press("Tab")
    print(f"搜索 {course_code}，等待服务器完成查询...")
    with page.expect_response(
        lambda response: (
            urlsplit(response.url).path == "/api/v1/Search/Search"
            and course_code.upper() in (response.request.post_data or "").upper()
        ),
        timeout=30000,
    ) as pending:
        page.locator("button.search-btn:not(.ivu-btn-long)").click()
    response = pending.value
    if response.status != 200:
        raise RuntimeError(f"试卷检索请求失败（HTTP {response.status}），请重新登录或稍后重试。")
    response.finished()
    page.wait_for_load_state("networkidle", timeout=30000)
    if search_input.input_value().strip().upper() != course_code.upper():
        raise RuntimeError("页面初始化重置了课程查询，请重试，未使用未筛选的结果。")
    if "/SearchDetail/" not in page.url:
        raise RuntimeError("未停留在试卷搜索页，请重新登录后重试。")


def detect_total_pages(page):
    """读取真实总页数；无法确定时失败，不猜测默认页数。"""
    total = page.evaluate("""() => {
        const app = window.PDFViewerApplication;
        return app?.pdfDocument?.numPages || app?.pagesCount || 0;
    }""")

    if not total:
        total_text = page.evaluate("""() => {
            const el = document.querySelector('#numPages');
            return el ? el.textContent : '';
        }""")
        match = re.search(r'(\d+)', total_text)
        total = int(match.group(1)) if match else 0

    if not total:
        raise RuntimeError("无法确认 PDF 总页数，请等待网站恢复后重试。")

    return total


def preload_pages(page, total):
    """快速遍历每一页触发渲染，再回到第一页"""
    print(f"预加载 {total} 页...")
    for i in range(1, total + 1):
        check_cancelled()
        page.evaluate("(n) => { PDFViewerApplication.page = n; }", i)
        page.wait_for_timeout(200)
    page.evaluate("() => { PDFViewerApplication.page = 1; }")
    page.wait_for_timeout(800)
    print("预加载完成")


def _capture_rendered_page(page, page_num, scale, timeout_ms=30000):
    """等待 PDF.js 在目标缩放下完成绘制，避免导出空白或旧尺寸画布。"""
    return page.evaluate(
        """async ({pageNum, scale, timeoutMs}) => {
            const app = window.PDFViewerApplication;
            if (!app?.pdfViewer?.getPageView) {
                return {ok: false, reason: 'PDFViewerApplication 未初始化'};
            }
            app.pdfViewer.currentScale = scale;
            app.page = pageNum;
            const deadline = Date.now() + timeoutMs;
            while (Date.now() < deadline) {
                const view = app.pdfViewer.getPageView(pageNum - 1);
                const canvas = document.querySelector(
                    '.page[data-page-number="' + pageNum + '"] canvas'
                );
                if (view?._renderError) {
                    return {ok: false, reason: String(view._renderError)};
                }
                // PDF.js 的 FINISHED=3；画布有宽高并不代表内容已经绘制。
                if (view?.renderingState === 3 &&
                    Math.abs(view.scale - scale) < 0.001 &&
                    canvas && canvas === view.canvas &&
                    canvas.width > 0 && canvas.height > 0) {
                    if (view.viewport &&
                        (canvas.width + 2 < view.viewport.width ||
                         canvas.height + 2 < view.viewport.height)) {
                        return {ok: false, reason: '画布分辨率低于目标缩放，未保存该页'};
                    }
                    return {
                        ok: true,
                        dataURL: canvas.toDataURL('image/png'),
                        width: canvas.width,
                        height: canvas.height,
                    };
                }
                await new Promise(resolve => setTimeout(resolve, 100));
            }
            return {ok: false, reason: '等待目标缩放下的页面绘制完成超时'};
        }""",
        {"pageNum": page_num, "scale": scale, "timeoutMs": timeout_ms},
    )


def extract_canvas_pages(page, output_dir, scale=2.0):
    """
    逐页提取 Canvas 为 PNG，保存到 output_dir。
    返回成功提取的页数。
    """
    total = detect_total_pages(page)
    emit("pages", done=0, total=total)
    preload_pages(page, total)

    os.makedirs(output_dir, exist_ok=True)
    print(f"缩放 {scale}x，开始提取 {total} 页...")

    success = 0
    for i in range(1, total + 1):
        check_cancelled()
        result = _capture_rendered_page(page, i, scale)

        if not result.get("ok"):
            print(f"  第 {i:03d} 页: 失败 ({result.get('reason', 'unknown')})")
            continue

        _, encoded = result["dataURL"].split(",", 1)
        img_data = base64.b64decode(encoded)

        filename = f"pdf_page_{i:03d}.png"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "wb") as f:
            f.write(img_data)

        success += 1
        emit("pages", done=success, total=total)
        check_cancelled()
        print(f"  第 {i:03d} 页 ✓ ({result['width']}×{result['height']}) → {filename}")

    print(f"提取完成，成功 {success}/{total} 页 → {output_dir}/")
    if success != total:
        raise RuntimeError(f"页面未完整提取：成功 {success}/{total} 页，请重试。")
    return success


# ═══════════════════════════════════════════════════════════════
# 搜索结果收集（新增）
# ═══════════════════════════════════════════════════════════════

def collect_search_results(page):
    """从当前搜索结果页抓取试卷链接及其所在结果行的文字。"""
    return page.evaluate("""() => {
        const links = document.querySelectorAll("a[href*='PaperDetail']");
        return Array.from(links).map((a, i) => {
            const row = a.closest('tr, li, .el-table__row') || a.parentElement;
            return {
                href: a.href,
                text: (a.textContent || '').trim().substring(0, 300),
                site_text: (row?.innerText || '').trim().substring(0, 1500),
                index: i
            };
        });
    }""")


def has_next_page(page):
    """检测搜索结果是否有下一页"""
    selectors = [
        ".el-pagination button.btn-next:not([disabled])",
        ".el-pager + button:not([disabled])",
        "button:has-text('Next')",
        "a:has-text('Next')",
        "[class*='pagination'] button:last-child:not([disabled])",
        ".el-icon-arrow-right",
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_enabled():
                return True
        except Exception:
            pass
    return False


def go_to_next_page(page):
    """点击下一页，等待结果加载。返回是否成功。"""
    selectors = [
        ".el-pagination button.btn-next",
        ".el-pager + button",
        "button:has-text('Next')",
        "a:has-text('Next')",
        "[class*='pagination'] button:last-child",
        ".el-icon-arrow-right",
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_enabled():
                url_before = page.url
                el.click()
                page.wait_for_timeout(2000)
                return True
        except Exception:
            pass
    return False


# ═══════════════════════════════════════════════════════════════
# 向后兼容入口
# ═══════════════════════════════════════════════════════════════

def capture_canvas(scale=2.0, course_code=None):
    """兼容旧入口：仅导出搜索结果中的第一套 PDF，同样执行完整校验。"""
    from batch_capture import PaperLink, extract_one_paper
    from pdf_output import normalize_course_code, validate_scale

    course_code = normalize_course_code(course_code or os.environ.get("XJTLU_COURSE", ""))
    validate_scale(scale)
    with sync_playwright() as playwright:
        with open_chrome(playwright, headless=False, user_data_dir=SPECIAL_PROFILE) as (context, persistent):
            page = context.new_page() if persistent else (
                context.pages[0] if context.pages else context.new_page()
            )
            page.set_viewport_size(VIEWPORT)
            exam_tab = None
            try:
                login(page)
                exam_tab = navigate_to_past_exam_papers(page)
                agree_and_search(exam_tab, course_code)
                papers = collect_search_results(exam_tab)
                if not papers:
                    raise RuntimeError(f"未找到 {course_code} 的试卷")
                first = papers[0]
                paper = PaperLink(first["href"], first["text"], first["index"],
                                  1, first.get("site_text", ""))
                result = extract_one_paper(context, exam_tab, paper, scale, course_code)
                if not result.success:
                    raise RuntimeError(result.error)
                print(f"完成并校验: {result.output_file}")
            finally:
                if persistent:
                    for tab in (exam_tab, page):
                        try:
                            if tab is not None and not tab.is_closed():
                                tab.close()
                        except Exception:
                            pass


if __name__ == "__main__":
    import sys
    scale = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
    course_code = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("XJTLU_COURSE", "")
    if not course_code:
        course_code = input("请输入课程代码: ").strip()
    capture_canvas(scale=scale, course_code=course_code)
