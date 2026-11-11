'use strict';
const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="paperforge-token"]').content;
let stopped = false;
let lastResults = '';
const labels = {pending:'等待中', working:'整理中', complete:'已校验', partial:'部分完成', failed:'未完成', empty:'无结果'};
function error(message) { $('error').textContent = message; $('error').hidden = !message; }
function courses() { return [...new Set($('courses').value.toUpperCase().split(/[\s,，、;；]+/).filter(Boolean))]; }
function element(tag, className, text) { const el = document.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = text; return el; }
async function api(path, body) {
  const options = {headers:{'X-PaperForge-Token':token}};
  if (body !== undefined) Object.assign(options, {method:'POST', body:JSON.stringify(body), headers:{...options.headers, 'Content-Type':'application/json'}});
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || '操作未完成，请重试。');
  return value;
}
$('courses').addEventListener('input', () => {
  $('course-chips').replaceChildren(...courses().map(code => element('span', /^([A-Z]{3})\d{3}[A-Z]{0,2}$/.test(code) ? 'chip' : 'chip invalid', code)));
  error('');
});
$('export-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const codes = courses();
  if (!codes.length || codes.length > 20 || codes.some(code => !/^[A-Z]{3}\d{3}[A-Z]{0,2}$/.test(code))) return error('请填写有效课程编号，例如 ABC123；一次最多 20 门。');
  error(''); $('submit').disabled = true;
  try { await api('/api/export', {courses:codes, scale:Number(document.querySelector('input[name="quality"]:checked').value)}); await refresh(); }
  catch (e) { error(e.message); $('submit').disabled = false; }
});
$('login').addEventListener('click', async () => { error(''); try { await api('/api/login', {}); await refresh(); } catch(e) { error(e.message); } });
$('open-output').addEventListener('click', async () => { try { await api('/api/open-output', {}); } catch(e) { error(e.message); } });
$('quit').addEventListener('click', async () => {
  try { await api('/api/shutdown', {}); stopped = true; $('phase').textContent = '已退出'; error('应用已退出，可以关闭此窗口。下次调用 skill 即可重新打开。'); $('submit').disabled = true; $('login').disabled = true; $('open-output').disabled = true; $('quit').disabled = true; }
  catch(e) { error(e.message); }
});
function render(state) {
  $('submit').disabled = state.active;
  $('login').disabled = state.active;
  $('quit').disabled = state.active;
  $('submit').firstElementChild.textContent = state.active ? '正在整理，请稍候…' : '开始整理试卷';
  $('account-dot').classList.toggle('connected', state.login_ready);
  $('account-label').textContent = state.login_ready ? '学校账号 · 已连接' : '学校账号 · 按需连接';
  $('login').firstChild.textContent = state.login_ready ? '检查连接 ' : '连接账号 ';
  $('output-path').textContent = state.output_dir;
  $('output-path').title = state.output_dir;
  const phaseNames = {idle:'准备就绪', login:'等待连接', export:'正在整理', done:'已完成', review:'需要核对', error:'未完成'};
  $('phase').textContent = phaseNames[state.phase] || '准备就绪';
  $('phase').className = 'phase' + (state.active ? ' busy' : ['error','review'].includes(state.phase) ? ' review' : '');
  $('empty').hidden = state.phase !== 'idle';
  $('job').hidden = state.phase === 'idle';
  $('message').textContent = state.message;
  $('step-login').classList.toggle('active', state.phase === 'login');
  $('step-search').classList.toggle('active', state.phase === 'export');
  $('step-done').classList.toggle('active', ['done','review'].includes(state.phase));
  const current = state.results.find(r => r.status === 'working');
  const fraction = current && current.expected ? current.papers.length / current.expected : 0;
  $('progress').value = state.results.length ? 100 * (state.finished + fraction) / state.results.length : (state.phase === 'done' ? 100 : 0);
  const serialized = JSON.stringify(state.results);
  if (serialized === lastResults) return;
  lastResults = serialized;
  $('results').replaceChildren(...state.results.map(row => {
    const card = element('article', 'result ' + row.status);
    const head = element('div', 'result-head');
    head.append(element('span', 'course-name', row.course), element('span', 'result-status', labels[row.status]));
    card.append(head, element('p', 'result-message', row.message));
    if (row.papers.length) {
      const files = element('ul', 'file-list');
      row.papers.forEach(paper => { const li = element('li'); li.append(element('span', '', paper.name), element('span', '', `${paper.pages} 页`)); files.append(li); });
      card.append(files);
    }
    return card;
  }));
}
async function refresh() {
  if (stopped) return;
  try { render(await api('/api/status')); }
  catch(e) { if (!stopped) { $('phase').textContent = '连接中断'; error('本地应用暂时无法连接，请重新调用 skill 打开。'); } }
}
async function poll() { await refresh(); if (!stopped) setTimeout(poll, 1000); }
poll();
