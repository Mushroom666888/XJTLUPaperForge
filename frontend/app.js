'use strict';
const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="paperforge-token"]').content;
const coursePattern = /^[A-Z]{3}\d{3}[A-Z]{0,2}$/;
const labels = {pending:'等待中', working:'整理中', complete:'已校验', partial:'部分完成', failed:'未完成', empty:'无结果', cancelled:'已取消'};
const moods = {
  idle: ['idle', '哪门课？让我想想。', '准备就绪'],
  starting: ['starting', '好，准备出发。', '正在连接'],
  login: ['starting', '先和学校打个招呼。', '正在连接'],
  waiting: ['idle', '请去登录哦', '等待登录'],
  searching: ['searching', '让我仔细找一找。', '搜索试卷'],
  downloading: ['downloading', '正在把试卷带回来。', '下载页面'],
  validating: ['validating', '每一页，都要检查好。', '校验 PDF'],
  connected: ['starting', '连接好了，随时出发。', '账号已连接'],
  done: ['success', '整理好啦，安心复习吧。', '归档完成'],
  review: ['issue', '有几份，还需要看看。', '需要核对'],
  error: ['issue', '遇到一点小状况。', '未完成'],
  cancelling: ['validating', '好，我们先停一下。', '正在停止'],
  cancelled: ['validating', '休息一下，下次接着来。', '已取消'],
};
let stopped = false;
let pending = false;
let offline = false;
let latestState = null;
let lastResults = '';
let lastBrowserInfo = '';
let refreshSequence = 0;
let toastTimer;
function error(message, invalidInput = false) {
  $('error').textContent = message;
  $('error').hidden = !message;
  $('courses').setAttribute('aria-invalid', String(invalidInput));
}
function toast(message) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4500);
}
function courses() { return [...new Set($('courses').value.toUpperCase().split(/[\s,，、;；]+/).filter(Boolean))]; }
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
async function api(path, body) {
  const options = {headers: {'X-PaperForge-Token': token}};
  if (body !== undefined) Object.assign(options, {method:'POST', body:JSON.stringify(body), headers:{...options.headers, 'Content-Type':'application/json'}});
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || '操作未完成，请重试。');
  return value;
}
function controls() {
  const busy = pending || stopped || offline || !latestState || latestState.active || latestState.folder_busy;
  ['submit', 'login', 'change-output', 'reset-output', 'quit', 'courses', 'browser-choice', 'save-browser'].forEach(id => { $(id).disabled = Boolean(busy); });
  if (latestState?.browser && !latestState.browser.selected) { $('submit').disabled = true; $('login').disabled = true; }
  if (!$('browser-choice').value) $('save-browser').disabled = true;
  document.querySelectorAll('input[name="quality"]').forEach(input => { input.disabled = Boolean(busy); });
  $('open-output').disabled = pending || stopped || offline || !latestState;
  $('open-results').disabled = pending || stopped || offline;
  $('cancel').disabled = pending || stopped || offline || latestState?.phase === 'cancelling';
}
async function action(path, body = {}, success) {
  if (pending || stopped) return;
  pending = true;
  error(''); controls();
  try {
    const result = await api(path, body);
    if (success) success(result);
    await refresh();
  } catch (e) { error(e.message); }
  finally { pending = false; controls(); }
}
$('courses').addEventListener('input', () => {
  $('course-chips').replaceChildren(...courses().map(code => element('span', coursePattern.test(code) ? 'chip' : 'chip invalid', code)));
  error('');
});
$('export-form').addEventListener('submit', async event => {
  event.preventDefault();
  const codes = courses();
  if (!codes.length || codes.length > 20 || codes.some(code => !coursePattern.test(code))) {
    error('请填写有效课程编号，例如 CAN209；一次最多 20 门。', true);
    $('courses').focus(); return;
  }
  await action('/api/export', {courses:codes, scale:Number(document.querySelector('input[name="quality"]:checked').value)}, () => {
    if (matchMedia('(max-width: 740px)').matches) document.querySelector('.activity').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block:'start'});
  });
});
$('login').addEventListener('click', () => action('/api/login'));
$('browser-choice').addEventListener('change', controls);
$('save-browser').addEventListener('click', () => action('/api/browser', {browser:$('browser-choice').value}, () => toast('浏览器已选择，接下来会在其中登录学校账号。')));
$('cancel').addEventListener('click', () => action('/api/cancel'));
$('open-output').addEventListener('click', () => action('/api/open-output'));
$('open-results').addEventListener('click', () => action('/api/open-output', {job:true}));
$('change-output').addEventListener('click', () => action('/api/output/select', {}, result => toast(result.changed ? '保存位置已更新，下次整理会使用新位置。' : '已保留原来的保存位置。')));
$('reset-output').addEventListener('click', () => action('/api/output/reset', {}, () => toast('已恢复默认保存位置。')));
$('quit').addEventListener('click', () => action('/api/shutdown', {}, () => {
  stopped = true;
  document.body.dataset.phase = 'cancelled';
  $('phase').textContent = '已退出';
  $('message').textContent = '应用已退出。下次调用 skill 即可重新打开。';
  $('mood-title').textContent = '下次见。';
  $('cancel').hidden = true;
  toast('可以关闭这个窗口了。');
}));

function renderResults(rows) {
  const serialized = JSON.stringify(rows);
  if (serialized === lastResults) return;
  lastResults = serialized;
  const opened = new Set([...document.querySelectorAll('.result details[open]')].map(node => node.dataset.course));
  const focusedCourse = document.activeElement?.closest('details')?.dataset.course;
  $('results').replaceChildren(...rows.map(row => {
    const card = element('article', 'result ' + row.status);
    const head = element('div', 'result-head');
    head.append(element('span', 'course-name', row.course), element('span', 'result-status', labels[row.status]));
    card.append(head, element('p', 'result-message', row.message));
    if (row.papers.length) {
      const details = element('details'); details.dataset.course = row.course; details.open = opened.has(row.course);
      const summary = element('summary', '', `查看 ${row.papers.length} 份 PDF`);
      const files = element('ul', 'file-list');
      row.papers.forEach(paper => { const li = element('li'); li.append(element('span', '', paper.name), element('span', '', `${paper.pages} 页`)); files.append(li); });
      details.append(summary, files); card.append(details);
    }
    return card;
  }));
  if (focusedCourse) [...document.querySelectorAll('.result details')].find(node => node.dataset.course === focusedCourse)?.querySelector('summary').focus({preventScroll:true});
}
function render(state) {
  latestState = state;
  const browser = state.browser;
  if (browser) {
    $('browser-fallback').hidden = browser.chrome_available;
    const serialized = JSON.stringify(browser);
    if (serialized !== lastBrowserInfo) {
      lastBrowserInfo = serialized;
      $('browser-choice').replaceChildren(element('option', '', '请选择浏览器'), ...browser.choices.map(choice => {
        const option = element('option', '', choice.name); option.value = choice.id; return option;
      }));
      $('browser-choice').firstElementChild.value = '';
      $('browser-choice').value = browser.selected || '';
      $('browser-help').textContent = browser.choices.length ?
        (browser.selected ? `当前使用 ${browser.name}。检测到 Chrome 后会自动优先使用 Chrome。` : '请选择已安装的兼容浏览器，学校账号需要在该浏览器重新登录。') :
        '还没有检测到兼容浏览器。请安装 Chrome 后刷新；Firefox 和 Safari 暂不支持后台试卷读取。';
    }
  }
  controls();
  const phase = state.phase;
  const [mood, title, label] = moods[phase] || moods.idle;
  document.body.dataset.phase = phase;
  document.body.dataset.mood = mood;
  document.body.dataset.running = String(state.active);
  const source = `/assets/${mood}.png`;
  if ($('companion').getAttribute('src') !== source) $('companion').src = source;
  $('mood-title').textContent = title;
  $('phase').textContent = label;
  $('phase').className = 'phase' + (['error','review'].includes(phase) ? ' review' : '');
  if ($('message').textContent !== state.message) $('message').textContent = state.message;
  $('submit').firstElementChild.textContent = state.active ? (phase === 'waiting' ? '正在等待登录…' : '正在整理中…') : ['error','review','cancelled'].includes(phase) ? '重新整理试卷' : '开始整理试卷';
  $('change-output').textContent = state.folder_busy ? '请在系统窗口选择…' : '更改位置';
  $('account-dot').classList.toggle('connected', state.login_ready);
  $('account-label').textContent = phase === 'waiting' ? '学校账号 · 等待登录' : state.login_ready ? '学校账号 · 已连接' : '学校账号 · 按需连接';
  $('login').textContent = state.login_ready ? '检查连接' : '连接账号';
  $('output-path').textContent = state.output_dir;
  $('output-path').title = state.output_dir;
  $('reset-output').title = `恢复默认位置：${state.default_output_dir}`;
  const stage = ['starting','waiting','login'].includes(phase) ? 'login' : phase;
  document.querySelectorAll('.steps li').forEach(li => {
    const active = li.dataset.step === stage;
    li.classList.toggle('active', active);
    if (active) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
  });
  // This is a course-completion counter, not a time estimate or a guessed file %.
  const complete = state.results.filter(row => row.status === 'complete').length;
  const verified = state.results.reduce((count, row) => count + row.papers.length, 0);
  $('progress').max = Math.max(1, state.results.length);
  $('progress').value = complete;
  $('progress-count').textContent = state.results.length ? `${complete} / ${state.results.length} 门` : '等待开始';
  $('progress').setAttribute('aria-valuetext', state.results.length ? `${complete} 门课程已完成归档，共 ${state.results.length} 门；${verified} 份 PDF 已校验` : '尚未开始归档');
  const current = state.results.find(row => row.status === 'working');
  const detail = current?.expected != null ? `${current.course}：${current.papers.length} / ${current.expected} 份 PDF 已校验` :
    state.active ? (stage === 'login' ? '连接时无需估计进度，登录完成后自动继续。' : `正在搜索 ${state.current_course}，文件总数待确认。`) :
    state.results.length ? `共 ${verified} 份 PDF 已通过校验${phase === 'done' ? '，已保存到本地。' : '；未完成的课程可重新整理。'}` : '真实进度，会在这里一步步留下足迹。';
  if ($('progress-detail').textContent !== detail) $('progress-detail').textContent = detail;
  $('current-work').hidden = !state.active || !state.current_file;
  $('current-file').textContent = (state.retrying ? '重试中 · ' : '') + state.current_file;
  $('page-count').textContent = state.pages_total == null ? '等待页面信息' : `${state.pages_done} / ${state.pages_total} 页已读取`;
  $('cancel').hidden = !state.active;
  $('open-results').hidden = !verified;
  $('idle-note').hidden = state.results.length > 0 || state.active;
  $('job-path').hidden = !state.results.length || !state.job_output_dir;
  $('job-path').textContent = `本次归档：${state.job_output_dir || ''}`;
  renderResults(state.results);
  if (state.warning) error(state.warning);
}
async function refresh() {
  if (stopped) return;
  const sequence = ++refreshSequence;
  try {
    const state = await api('/api/status');
    if (sequence !== refreshSequence || stopped) return;
    if (offline) { offline = false; error(''); }
    render(state);
  } catch (e) {
    if (!stopped && sequence === refreshSequence) {
      offline = true;
      document.body.dataset.phase = 'error';
      $('companion').src = '/assets/issue.png';
      $('phase').textContent = '连接中断';
      $('mood-title').textContent = '连接暂时中断了。';
      error('本地应用暂时无法连接，正在重连。若应用已关闭，请重新调用 skill 打开。');
      controls();
    }
  }
}
async function poll() { await refresh(); if (!stopped) setTimeout(poll, document.hidden ? 3000 : 850); }
document.addEventListener('visibilitychange', () => { document.body.classList.toggle('is-hidden', document.hidden); });
const visibility = new IntersectionObserver(entries => { document.body.classList.toggle('is-offscreen', !entries[0].isIntersecting); });
visibility.observe(document.querySelector('.activity'));
// Preload the small local plates so the first phase change never flashes blank.
Object.values(moods).map(item => item[0]).filter((item, index, all) => all.indexOf(item) === index).forEach(mood => { const image = new Image(); image.src = `/assets/${mood}.png`; });
controls();
poll();
