"""Local-only browser interface for XJTLUPaperForge."""

import argparse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
from socketserver import TCPServer
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

from settings import DATA_ROOT, OUTPUT_ROOT, PROJECT_ROOT
from output_preferences import OutputPreferences, choose_directory, validate_directory, course_directory
from task_events import PREFIX, TaskCancelled
from browser_config import BrowserPreferences, NAMES, open_workbench
from instance_lock import workbench_lock
from platform_support import open_directory
from runtime_paths import script_command, public_build_info
from result_audit import consume_result, set_expected, add_error, audit_files, finalize_result

APP_NAME = 'XJTLUPaperForge'
BUILD_INFO = public_build_info()
COURSE_RE = re.compile(r'[A-Z]{3}\d{3}[A-Z]{0,2}')
FRONTEND = PROJECT_ROOT / 'frontend'


def validate_export(payload):
    courses = payload.get('courses')
    if not isinstance(courses, list) or not 1 <= len(courses) <= 20:
        raise ValueError('请输入 1 至 20 个课程编号。')
    normalized = []
    for value in courses:
        if not isinstance(value, str) or not COURSE_RE.fullmatch(value.strip().upper()):
            raise ValueError('课程编号格式有误，例如 ABC123。')
        code = value.strip().upper()
        if code not in normalized:
            normalized.append(code)
    scale = payload.get('scale', 2.0)
    if isinstance(scale, bool) or scale not in (2, 3.125):
        raise ValueError('请选择 192 DPI 或 300 DPI。')
    return normalized, float(scale)


def public_error(line):
    if '清单' in line or '试卷总数' in line or '搜索结果未更新' in line:
        # These are credential-free reconciliation diagnostics, useful for missing papers.
        return line[:500]
    if '课程编号' in line:
        return '试卷课程编号不匹配或无法确认，未导出；请核对该条目。'
    if '封面的学年不一致' in line or '封面的考试类型不一致' in line:
        return '网站信息与实际试卷的学年或考试类型不一致，未发布；请核对该条目。'
    if '名称冲突' in line:
        return '不同试卷使用了相同归档名称，已保留原文件，请核对网站信息。'
    if '课程编号与请求不一致' in line:
        return '试卷课程编号与请求不一致，未将其他课程试卷归档。'
    if '封存' in line or 'embargoed' in line.lower():
        return '网站将部分试卷封存，当前没有阅读入口。'
    if '已有文件' in line or 'File exists' in line:
        return '已有文件不满足本次要求，已保留原文件。请更换保存位置或自行移走旧文件后重试。'
    if '分辨率' in line:
        return '页面未达到所选清晰度，已保留原有文件。'
    if any(word in line for word in ('空白', '重复', '页数', '像素')):
        return '部分页面未通过完整性检查，未发布不完整文件。'
    if '考试类型' in line:
        return '无法确认部分试卷的考试类型，需核对网站信息。'
    if 'timeout' in line.lower() or '超时' in line:
        return '学校网站响应超时，可在网络恢复后重试。'
    return '部分试卷未能完成，可重试；已完成文件会自动复用。'


class Jobs:
    def __init__(self, runner=None, preferences=None, picker=None, browsers=None):
        self.lock = threading.RLock()
        self.runner = runner or self.run_script
        self.preferences = preferences or OutputPreferences()
        self.picker = picker or choose_directory
        self.browsers = browsers or BrowserPreferences(self.preferences.file.parent)
        self.job_browser = None
        self.cancel_requested = threading.Event()
        self.cancel_file = None
        self.closing = False
        self.state = {'build': BUILD_INFO, 'active': False, 'phase': 'idle', 'message': '想找哪门课？我来帮你整理。',
                      'login_ready': False, 'results': [], 'output_dir': str(self.preferences.path),
                      'default_output_dir': str(self.preferences.default), 'job_output_dir': None,
                      'finished': 0, 'folder_busy': False, 'warning': self.preferences.warning,
                      'current_course': '', 'current_file': '', 'pages_done': 0, 'pages_total': None,
                      'retrying': False, 'kind': None}

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(dict(self.state, browser=self.browsers.info())))

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def select_browser(self, key):
        with self.lock:
            if self.closing or self.state['active'] or self.state['folder_busy']:
                raise RuntimeError('请先结束当前任务或文件夹选择。')
            self.browsers.select(key)
            self.state['login_ready'] = False

    def change_output(self, reset=False):
        with self.lock:
            if self.closing or self.state['active'] or self.state['folder_busy']:
                raise RuntimeError('任务或文件夹选择正在进行，请稍候。')
            self.state['folder_busy'] = True
        try:
            selected = str(self.preferences.default) if reset else self.picker(self.preferences.path)
            if selected is None:
                return False
            path = self.preferences.save(selected, create=reset)
            self.update(output_dir=str(path), warning='')
            return True
        finally:
            self.update(folder_busy=False)

    def start(self, kind, courses=None, scale=2):
        with self.lock:
            if self.closing or self.state['active'] or self.state['folder_busy']:
                raise RuntimeError('已有任务或文件夹选择正在进行，请稍候。')
            self.job_browser = self.browsers.require()
            output = validate_directory(self.preferences.path,
                                        create=self.preferences.path == self.preferences.default)
            self.cancel_requested.clear()
            marker_dir = self.preferences.file.parent / 'work'
            marker_dir.mkdir(parents=True, exist_ok=True)
            self.cancel_file = marker_dir / ('cancel-' + secrets.token_hex(12))
            self.state.update(active=True, phase='starting', finished=0, kind=kind,
                              current_course='', current_file='', pages_done=0, pages_total=None,
                              retrying=False, job_output_dir=str(output), output_dir=str(output),
                              message=f'正在连接学校；如弹出登录页面，请在 {self.browsers.info()["name"]} 中完成登录。')
            self.state['results'] = [dict(course=code, status='pending', expected=None,
                                         papers=[], errors=[], message='等待处理') for code in (courses or [])]
            threading.Thread(target=self.work, args=(kind, courses or [], scale), daemon=True).start()

    def cancel(self):
        with self.lock:
            if not self.state['active'] or self.state['phase'] in ('done', 'connected', 'review', 'error', 'cancelled'):
                return
            self.cancel_requested.set()
            if self.cancel_file:
                self.cancel_file.touch()
            self.state.update(phase='cancelling', message='正在停止，当前网络操作结束后退出。已校验的 PDF 会保留。')

    def prepare_shutdown(self):
        with self.lock:
            if self.state['active'] or self.state['folder_busy']:
                raise RuntimeError('任务或文件夹选择仍在进行，请结束后再退出。')
            self.closing = True

    def check_cancel(self):
        if self.cancel_requested.is_set():
            raise TaskCancelled()

    def run_script(self, script, args, on_line):
        log_dir = DATA_ROOT / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        log = log_dir / f'{datetime.now():%Y%m%d-%H%M%S-%f}-{Path(script).stem}.log'
        environment = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1',
                           XJTLUPAPERFORGE_EVENTS='1',
                           XJTLUPAPERFORGE_OUTPUT=self.state['job_output_dir'] or self.state['output_dir'])
        if self.job_browser:
            environment['XJTLUPAPERFORGE_BROWSER'] = self.job_browser
        if self.cancel_file:
            environment['XJTLUPAPERFORGE_CANCEL_FILE'] = str(self.cancel_file)
        command = script_command(script, *args)
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        with log.open('w', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(build=BUILD_INFO, worker=script), ensure_ascii=False) + '\n')
            with subprocess.Popen(command, cwd=PROJECT_ROOT, env=environment, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, encoding='utf-8', errors='replace',
                                  creationflags=flags) as process:
                for line in process.stdout:
                    stream.write(line)
                    stream.flush()
                    on_line(line.strip())
                return process.wait()

    def consume(self, row, line):
        with self.lock:
            if line.startswith(PREFIX):
                try:
                    event = json.loads(line[len(PREFIX):])
                    if not isinstance(event, dict):
                        raise ValueError('Invalid event')
                except ValueError:
                    if row is not None:
                        add_error(row, '收到损坏的进度记录，无法确认任务完整。')
                    return
                kind = event.get('event')
                if kind == 'phase' and not self.cancel_requested.is_set():
                    phase = event.get('phase')
                    if phase in ('login', 'waiting', 'searching', 'downloading', 'validating'):
                        self.state.update(phase=phase)
                        if phase == 'waiting':
                            browser = NAMES.get(self.job_browser, '浏览器')
                            self.state.update(login_ready=False,
                                message=f'请在弹出的 {browser} 学校页面完成登录，登录后会自动继续。')
                        elif phase == 'login':
                            self.state['message'] = '正在检查学校连接，请稍候。'
                        else:
                            self.state.update(login_ready=True,
                                message=f'正在整理 {self.state["current_course"]}。')
                if row is None:
                    return
                consume_result(row, event)
                if kind == 'paper':
                    self.state.update(current_file=event.get('name', ''), pages_done=0,
                                      pages_total=None)
                    if 'retry' in event:
                        self.state['retrying'] = bool(event['retry'])
                elif kind == 'pages':
                    done, total = event.get('done'), event.get('total')
                    if type(done) is int and type(total) is int and 0 <= done <= total:
                        self.state.update(pages_done=done, pages_total=total)
                    else:
                        add_error(row, '收到无效的页数进度记录。')
                elif kind == 'fatal':
                    add_error(row, public_error(str(event.get('error', ''))))
                return
            if row is None:
                return
            found = re.search(r'共发现 (\d+) 套试卷', line)
            if found:
                try:
                    set_expected(row, int(found[1]))
                except ValueError as exc:
                    add_error(row, str(exc))
            if line.startswith('✗') or line.startswith('导出未完成:'):
                error = public_error(line)
                if error not in row['errors']:
                    row['errors'].append(error)

    def work(self, kind, courses, scale):
        try:
            self.check_cancel()
            login_code = self.runner('login.py', [], lambda line: self.consume(None, line))
            self.check_cancel()
            if login_code:
                self.update(login_ready=False, phase='error', message='登录未完成。请检查学校网页或网络，然后重试。')
                return
            self.update(login_ready=True)
            if kind == 'login':
                self.update(phase='connected', message='学校账号已连接，可以开始导出。')
                return
            for index, row in enumerate(self.state['results']):
                self.check_cancel()
                with self.lock:
                    row.update(status='working', message='正在搜索课程')
                    self.state.update(phase='searching', current_course=row['course'], current_file='',
                                      pages_done=0, pages_total=None, retrying=False,
                                      message=f"正在整理 {row['course']}")
                code = self.runner('batch_capture.py', [row['course'], '--scale', str(scale)],
                                   lambda line: self.consume(row, line))
                self.check_cancel()
                self.update(phase='validating', message=f"正在逐份复核 {row['course']} 的清单与磁盘文件。")
                disk_errors = audit_files(row, self.state['job_output_dir'] or self.state['output_dir'],
                                          scale, self.check_cancel)
                with self.lock:
                    finalize_result(row, code, disk_errors, public_error)
                    row['exit_code'] = code
                    self.state['finished'] = index + 1
            # A previous course can change on disk while later courses run.
            # Reconcile the whole job at the boundary where we announce success.
            if len(self.state['results']) > 1:
                self.update(phase='validating', message='正在复核本次所有课程的最终文件。')
                for row in self.state['results']:
                    disk_errors = audit_files(row, self.state['job_output_dir'] or self.state['output_dir'],
                                              scale, self.check_cancel)
                    with self.lock:
                        finalize_result(row, row['exit_code'], disk_errors, public_error)
            with self.lock:
                self.check_cancel()
                failures = any(r['status'] != 'complete' for r in self.state['results'])
                count = sum(len(r['papers']) for r in self.state['results'])
                totals_known = all(r['expected'] is not None for r in self.state['results'])
                total = sum(r['expected'] or 0 for r in self.state['results']) if totals_known else '?'
                self.state.update(phase='review' if failures else 'done',
                                  message=(f'归档未完成：已校验 {count}/{total} 份，请查看下方未完成原因。' if failures
                                           else f'归档完成：{count}/{total} 份 PDF 已通过清单与磁盘复核。'))
        except TaskCancelled:
            with self.lock:
                for row in self.state['results']:
                    if row['status'] in ('working', 'pending'):
                        row.update(status='cancelled', message='已停止，已校验的文件保留')
                self.state.update(phase='cancelled', message='已取消整理。已校验的 PDF 已保留，可随时重新开始。')
        except Exception:
            self.update(phase='error', message='任务未能完成，请检查本地环境后重试。已完成文件会保留。')
        finally:
            with self.lock:
                for row in self.state['results']:
                    if row['status'] in ('working', 'pending'):
                        row.update(status='failed', message='任务未完成，可重试')
                try:
                    if self.cancel_file:
                        self.cancel_file.unlink(missing_ok=True)
                finally:
                    self.state['active'] = False


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # HTTPServer's getfqdn() can block on macOS DNS before any request.
        # This loopback service needs only its bound address, never a DNS name.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def __init__(self, address=('127.0.0.1', 0), jobs=None):
        self.jobs = jobs or Jobs()
        self.token = secrets.token_urlsafe(32)
        self.instance = secrets.token_hex(16)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, value, content_type='application/json; charset=utf-8'):
        body = json.dumps(value, ensure_ascii=False).encode('utf-8') if isinstance(value, dict) else value
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
        try:
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # Closing the browser during a status poll is a normal disconnect.
            self.close_connection = True

    def allowed(self, api=False):
        host = f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') != host:
            self.send(403, {'error': '请求来源无效。'})
            return False
        origin = self.headers.get('Origin')
        if origin and origin != f'http://{host}':
            self.send(403, {'error': '请求来源无效。'})
            return False
        if api and not secrets.compare_digest(self.headers.get('X-PaperForge-Token', ''), self.server.token):
            self.send(403, {'error': '请刷新本地应用页面。'})
            return False
        return True

    def do_GET(self):
        if not self.allowed(api=self.path.startswith('/api/')):
            return
        if self.path == '/health':
            return self.send(200, {'app': APP_NAME, 'instance': self.server.instance, **BUILD_INFO})
        if self.path == '/api/status':
            return self.send(200, self.server.jobs.snapshot())
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8'),
                  '/icon.svg': ('icon.svg', 'image/svg+xml')}
        for mood in ('idle', 'starting', 'searching', 'downloading', 'validating', 'success', 'issue'):
            assets[f'/assets/{mood}.png'] = (f'assets/{mood}.png', 'image/png')
        if self.path not in assets:
            return self.send(404, {'error': '页面不存在。'})
        name, mime = assets[self.path]
        body = (FRONTEND / name).read_bytes()
        if name == 'index.html':
            body = body.replace(b'__APP_TOKEN__', self.server.token.encode('ascii'))
        self.send(200, body, mime)

    def do_POST(self):
        if not self.allowed(api=True):
            return
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= 8192:
                raise ValueError('请求大小无效。')
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError('请求格式无效。')
            if self.path == '/api/export':
                courses, scale = validate_export(payload)
                self.server.jobs.start('export', courses, scale)
            elif self.path == '/api/login':
                self.server.jobs.start('login')
            elif self.path == '/api/cancel':
                self.server.jobs.cancel()
            elif self.path == '/api/browser':
                self.server.jobs.select_browser(payload.get('browser'))
            elif self.path in ('/api/output/select', '/api/output/reset'):
                changed = self.server.jobs.change_output(reset=self.path.endswith('/reset'))
                return self.send(200, {'ok': True, 'changed': changed})
            elif self.path == '/api/open-output':
                state = self.server.jobs.snapshot()
                folder = Path((state['job_output_dir'] if payload.get('job') else None) or state['output_dir'])
                course = payload.get('course')
                if course:
                    courses, _ = validate_export({'courses': [course]})
                    folder = course_directory(folder, courses[0])
                folder = validate_directory(folder, create=True)
                open_directory(str(folder))
            elif self.path == '/api/shutdown':
                self.server.jobs.prepare_shutdown()
                self.send(200, {'ok': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            else:
                return self.send(404, {'error': '操作不存在。'})
            self.send(200, {'ok': True})
        except (ValueError, TypeError) as exc:
            self.send(400, {'error': str(exc) if isinstance(exc, ValueError) else '输入格式有误。'})
        except RuntimeError as exc:
            self.send(409, {'error': str(exc)})
        except OSError:
            self.send(500, {'error': '本地操作失败，请检查文件夹权限。'})


def existing_url(state_file):
    try:
        state = json.loads(state_file.read_text(encoding='utf-8'))
        if not isinstance(state, dict):
            return None
        if state.get('project_root') != str(PROJECT_ROOT):
            return None
        port = int(state['port'])
        if not 1 <= port <= 65535:
            return None
        url = f'http://127.0.0.1:{port}'
        with urlopen(url + '/health', timeout=1) as response:
            health = json.load(response)
        if isinstance(health, dict) and health.get('app') == APP_NAME and health.get('instance') == state.get('instance'):
            if any(health.get(key) != value for key, value in BUILD_INFO.items()):
                raise RuntimeError('该位置仍运行着其他版本的工作台，请先在旧工作台点击“退出应用”，再启动当前版本。')
            return url
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description=APP_NAME + ' 本地试卷工作台')
    parser.add_argument('--open', action='store_true', help='打开浏览器界面')
    args = parser.parse_args()
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    state_file = DATA_ROOT / 'ui.json'
    with workbench_lock(DATA_ROOT / 'ui.lock') as acquired:
        if not acquired:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if url := existing_url(state_file):
                    if args.open:
                        open_workbench(url, DATA_ROOT)
                    print(url, flush=True)
                    return
                time.sleep(.1)
            raise RuntimeError('工作台正在启动或退出，请稍后重试。')
        if url := existing_url(state_file):
            if args.open:
                open_workbench(url, DATA_ROOT)
            print(url, flush=True)
            return
        serve_workbench(state_file, args.open)


def serve_workbench(state_file, open_browser=False):
    server = Server()
    url = f'http://127.0.0.1:{server.server_port}'
    state_file.write_text(json.dumps({'port': server.server_port, 'instance': server.instance,
                                     'project_root': str(PROJECT_ROOT)}), encoding='utf-8')
    print(url, flush=True)
    try:
        if open_browser:
            open_workbench(url, DATA_ROOT)
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        try:
            if json.loads(state_file.read_text())['instance'] == server.instance:
                state_file.unlink()
        except (OSError, ValueError, KeyError):
            pass


if __name__ == '__main__':
    main()
