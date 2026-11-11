"""Local-only browser interface for XJTLUPaperForge."""

import argparse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
from urllib.request import urlopen
import webbrowser

from settings import DATA_ROOT, OUTPUT_ROOT, PROJECT_ROOT

APP_NAME = 'XJTLUPaperForge'
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
    if '封存' in line or 'embargoed' in line.lower():
        return '网站将部分试卷封存，当前没有阅读入口。'
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
    def __init__(self, runner=None):
        self.lock = threading.RLock()
        self.runner = runner or self.run_script
        self.state = {'active': False, 'phase': 'idle', 'message': '输入课程编号，开始整理试卷。',
                      'login_ready': False, 'results': [], 'output_dir': str(OUTPUT_ROOT), 'finished': 0}

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def start(self, kind, courses=None, scale=2):
        with self.lock:
            if self.state['active']:
                raise RuntimeError('已有任务正在进行，请等它完成。')
            self.state.update(active=True, phase='login', finished=0,
                              message='正在连接学校；如弹出登录页面，请在 Chrome 中完成登录。')
            if kind == 'export':
                self.state['results'] = [dict(course=code, status='pending', expected=None,
                                             papers=[], errors=[], message='等待处理') for code in courses]
            thread = threading.Thread(target=self.work, args=(kind, courses or [], scale), daemon=True)
            thread.start()

    def run_script(self, script, args, on_line):
        log_dir = DATA_ROOT / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        log = log_dir / f'{datetime.now():%Y%m%d-%H%M%S-%f}-{Path(script).stem}.log'
        environment = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1')
        command = [sys.executable, '-u', str(PROJECT_ROOT / script), *args]
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        with log.open('w', encoding='utf-8') as stream:
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
            found = re.search(r'共发现 (\d+) 套试卷', line)
            if found:
                row['expected'] = int(found[1])
                row['message'] = f'找到 {found[1]} 套，正在导出并校验'
            paper = re.search(r'✓ (.+\.pdf)（(\d+) 页，已校验）', line)
            if paper:
                if not any(p['name'] == paper[1] for p in row['papers']):
                    row['papers'].append(dict(name=paper[1], pages=int(paper[2])))
                row['message'] = f"已完成 {len(row['papers'])} 套"
            if line.startswith('✗') or line.startswith('导出未完成:'):
                error = public_error(line)
                if error not in row['errors']:
                    row['errors'].append(error)
            if '未找到' in line and '试卷' in line:
                row.update(expected=0, message='网站未找到该课程的试卷')

    def work(self, kind, courses, scale):
        try:
            login_code = self.runner('login.py', [], lambda line: None)
            if login_code:
                self.update(login_ready=False, phase='error', message='登录未完成。请检查学校网页或网络，然后重试。')
                return
            self.update(login_ready=True)
            if kind == 'login':
                self.update(phase='done', message='学校账号已连接，可以开始导出。')
                return
            for index, row in enumerate(self.state['results']):
                with self.lock:
                    row.update(status='working', message='正在搜索课程')
                    self.state.update(phase='export', message=f"正在整理 {row['course']}")
                code = self.runner('batch_capture.py', [row['course'], '--scale', str(scale)],
                                   lambda line: self.consume(row, line))
                with self.lock:
                    if code == 0 and row['expected'] == 0:
                        row.update(status='empty', message='网站未找到该课程的试卷')
                    elif code == 0 and row['papers'] and len(row['papers']) == row['expected']:
                        row.update(status='complete', message=f"{len(row['papers'])} 套已通过校验")
                    else:
                        row.update(status='partial' if row['papers'] else 'failed',
                                   message=row['errors'][0] if row['errors'] else public_error(''))
                    self.state['finished'] = index + 1
            with self.lock:
                failures = any(r['status'] in ('partial', 'failed') for r in self.state['results'])
                count = sum(len(r['papers']) for r in self.state['results'])
            self.update(phase='review' if failures else 'done',
                        message=f'处理结束，{count} 份 PDF 已通过校验。' + (' 部分课程需要重试。' if failures else ''))
        except Exception:
            self.update(phase='error', message='任务未能完成，请检查本地环境后重试。已完成文件会保留。')
        finally:
            self.update(active=False)


class Server(ThreadingHTTPServer):
    daemon_threads = True

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
        self.end_headers()
        self.wfile.write(body)

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
            return self.send(200, {'app': APP_NAME, 'instance': self.server.instance})
        if self.path == '/api/status':
            return self.send(200, self.server.jobs.snapshot())
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8'),
                  '/icon.svg': ('icon.svg', 'image/svg+xml')}
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
            elif self.path == '/api/open-output':
                folder = OUTPUT_ROOT
                course = payload.get('course')
                if course:
                    courses, _ = validate_export({'courses': [course]})
                    folder = folder / courses[0]
                folder.mkdir(parents=True, exist_ok=True)
                os.startfile(str(folder))
            elif self.path == '/api/shutdown':
                if self.server.jobs.snapshot()['active']:
                    raise RuntimeError('导出仍在进行，请完成后再退出。')
                self.send(200, {'ok': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            else:
                return self.send(404, {'error': '操作不存在。'})
            self.send(200, {'ok': True})
        except (ValueError, TypeError):
            self.send(400, {'error': '输入格式有误，请检查课程编号和清晰度。'})
        except RuntimeError as exc:
            self.send(409, {'error': str(exc)})
        except OSError:
            self.send(500, {'error': '本地操作失败，请检查文件夹权限。'})


def existing_url(state_file):
    try:
        state = json.loads(state_file.read_text(encoding='utf-8'))
        if state.get('project_root') != str(PROJECT_ROOT):
            return None
        port = int(state['port'])
        if not 1 <= port <= 65535:
            return None
        url = f'http://127.0.0.1:{port}'
        with urlopen(url + '/health', timeout=1) as response:
            health = json.load(response)
        if health.get('app') == APP_NAME and health.get('instance') == state.get('instance'):
            return url
    except (OSError, ValueError, KeyError):
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description=APP_NAME + ' 本地试卷工作台')
    parser.add_argument('--open', action='store_true', help='打开浏览器界面')
    args = parser.parse_args()
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    state_file = DATA_ROOT / 'ui.json'
    if url := existing_url(state_file):
        if args.open:
            webbrowser.open(url)
        print(url)
        return
    server = Server()
    url = f'http://127.0.0.1:{server.server_port}'
    state_file.write_text(json.dumps({'port': server.server_port, 'instance': server.instance,
                                     'project_root': str(PROJECT_ROOT)}), encoding='utf-8')
    print(url, flush=True)
    if args.open:
        webbrowser.open(url)
    try:
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
