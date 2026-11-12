"""Independent reconciliation of a frozen school inventory and actual output files."""
import hashlib
import json
from pathlib import Path
import re

ID_PATTERN = re.compile(r'[0-9a-f]{64}')


def record_id(href):
    return hashlib.sha256(href.encode('utf-8')).hexdigest()


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def catalog_items(papers):
    return [{'id':record_id(p.href),'label':(p.site_text or p.text or f'试卷 {i}')[:300]}
            for i,p in enumerate(papers,1)]


def verified_fields(result):
    return {'id':record_id(result.paper.href),'name':Path(result.output_file).name,
            'pages':result.page_count,'sha256':file_sha256(result.output_file)}


def add_error(row, message):
    if message not in row['errors']:
        row['errors'].append(message)


def set_expected(row, total):
    if type(total) is not int or total < 0:
        raise ValueError('收到无效的试卷总数。')
    if row['expected'] is None:
        row['expected'] = total
    elif total != row['expected']:
        raise ValueError(f"试卷总数发生变化：最初 {row['expected']} 份，后来 {total} 份；需要重新核对。")


def consume_result(row, event):
    """Only explicit inventory/results may affect completion; log prose cannot."""
    kind = event.get('event')
    try:
        if kind in ('inventory', 'catalog'):
            set_expected(row, event.get('total'))
            if kind == 'inventory':
                row['inventory_received'] = True
            if kind == 'catalog':
                if not row.get('inventory_received'):
                    raise ValueError('未先收到学校独立试卷总数，不能用清单长度代替。')
                items = event.get('items')
                if not isinstance(items, list) or len(items) != row['expected']:
                    raise ValueError('试卷清单条数与最初总数不一致或缺少逐份清单。')
                catalog = {}
                for item in items:
                    if (not isinstance(item, dict) or not isinstance(item.get('id'), str)
                            or not ID_PATTERN.fullmatch(item['id']) or item['id'] in catalog
                            or not isinstance(item.get('label'), str) or not item['label'].strip()):
                        raise ValueError('试卷清单包含无效或重复条目。')
                    catalog[item['id']] = item['label'][:300]
                if 'catalog' in row and row['catalog'] != catalog:
                    raise ValueError('逐份试卷清单发生变化，不能宣布完成。')
                row['catalog'] = catalog
            row['message'] = f"学校显示 {row['expected']} 份，正在核对并导出"
        elif kind in ('verified', 'paper_failed'):
            item_id = event.get('id')
            if not isinstance(item_id, str) or item_id not in row.get('catalog', {}):
                raise ValueError('收到不属于原始清单的试卷结果。')
            successes = row.setdefault('verified_by_id', {})
            failures = row.setdefault('failed_by_id', {})
            if kind == 'verified':
                name, pages, digest = event.get('name'), event.get('pages'), event.get('sha256')
                if (not isinstance(name, str) or not name.startswith(row['course'] + '_')
                        or not name.endswith('.pdf') or '/' in name or '\\' in name or ':' in name
                        or type(pages) is not int or pages < 1
                        or not isinstance(digest, str) or not ID_PATTERN.fullmatch(digest)):
                    raise ValueError('试卷成功记录缺少有效文件名、页数或文件校验值。')
                item = dict(id=item_id, name=name, pages=pages, sha256=digest)
                if item_id in failures or (item_id in successes and successes[item_id] != item):
                    raise ValueError('同一试卷的处理结果互相矛盾。')
                if any(other['name'].casefold() == name.casefold() for key, other in successes.items() if key != item_id):
                    raise ValueError('多份试卷指向同一个文件，不能计为多份成功。')
                successes[item_id] = item
                row['papers'] = list(successes.values())
            else:
                if item_id in successes:
                    raise ValueError('同一试卷同时被报告为成功和失败。')
                reason = event.get('error')
                if not isinstance(reason, str) or not reason.strip():
                    raise ValueError('试卷失败记录缺少有效的失败原因。')
                failures[item_id] = reason
            row['message'] = f"已校验 {len(successes)}/{row['expected']} 份"
        elif kind == 'summary':
            set_expected(row, event.get('total'))
            summary = {key: event.get(key) for key in ('total', 'succeeded', 'failed')}
            for key in ('succeeded', 'failed'):
                values = summary[key]
                if (not isinstance(values, list) or not all(isinstance(v, str) for v in values)
                        or len(values) != len(set(values))):
                    raise ValueError('结束记录缺少有效的逐份处理结果。')
            if 'summary' in row and row['summary'] != summary:
                raise ValueError('收到互相矛盾的结束记录。')
            row['summary'] = summary
    except ValueError as exc:
        add_error(row, str(exc))


def audit_files(row, output_root, scale, check_cancel=lambda: None):
    """Do not trust success text: each planned record must map to its own valid file."""
    from output_preferences import course_directory
    from pdf_quality import verify_pdf
    from pypdf import PdfReader
    errors = {}; seen = set()
    try:
        folder = course_directory(output_root, row['course'])
    except (OSError, ValueError, RuntimeError):
        return {item_id: '课程文件夹位置异常或无法访问，未计为成功。'
                for item_id in row.get('verified_by_id', {})}
    for item_id, item in row.get('verified_by_id',{}).items():
        check_cancel()
        name=item.get('name','')
        if not isinstance(name,str) or Path(name).name!=name or not name.endswith('.pdf'):
            errors[item_id] = '导出文件名无效。';continue
        try:
            target=folder/name
            key=str(target.resolve()).casefold()
            if target.is_symlink() or target.resolve().parent!=folder.resolve() or key in seen:
                raise ValueError('多个试卷指向同一文件或文件位置异常')
            seen.add(key)
            if file_sha256(target)!=item.get('sha256'):
                raise ValueError('文件内容与导出记录不一致')
            with target.open('rb') as stream:
                manifest = json.loads(PdfReader(stream, strict=True).metadata.get('/Subject', '{}'))
            source = manifest.get('source', {})
            if source.get('record_sha256') != item_id or source.get('course') != row['course']:
                raise ValueError('PDF 来源与原始试卷清单不一致')
            verify_pdf(target,item['pages'],min_dpi=96*scale)
            if file_sha256(target) != item['sha256']:
                raise ValueError('文件在复核时被修改')
        except Exception as exc:
            from task_events import TaskCancelled
            if isinstance(exc,TaskCancelled):raise
            reason = '文件不存在' if isinstance(exc, FileNotFoundError) else '文件内容、来源或页面完整性检查未通过'
            errors[item_id] = f'{name}：{reason}，未计为成功。'
    return errors


def finalize_result(row, exit_code, disk_errors, error_message):
    catalog = row.get('catalog', {})
    reported = row.get('verified_by_id', {})
    failures = row.get('failed_by_id', {})
    summary = row.get('summary')
    if not row.get('inventory_received'):
        add_error(row, '未收到学校独立试卷总数，无法确认搜索范围完整。')
    if row['expected'] is None or 'catalog' not in row:
        add_error(row, '未收到完整试卷清单，无法核实是否全部导出。')
    if summary is None:
        add_error(row, '没有收到逐份核对的结束记录，任务可能提前中断。')
    elif (summary['total'] != row['expected']
          or set(summary['succeeded']) != set(reported) or set(summary['failed']) != set(failures)
          or set(reported) & set(failures) or set(reported) | set(failures) != set(catalog)):
        add_error(row, '结束记录与原始清单或逐份结果不一致，不能宣布完成。')
    if exit_code:
        add_error(row, f'导出进程异常结束（退出码 {exit_code}）。')
    for item_id, reason in failures.items():
        add_error(row, f"{catalog.get(item_id, '试卷')}：{error_message(reason)}")
    for reason in disk_errors.values():
        add_error(row, reason)
    row['papers'] = [item for key, item in reported.items() if key not in disk_errors]
    good_ids = {item['id'] for item in row['papers']}
    row['missing'] = [{'id': key, 'label': label} for key, label in catalog.items() if key not in good_ids]
    for item in row['missing']:
        if item['id'] not in failures and item['id'] not in disk_errors:
            add_error(row, f"{item['label']}：没有收到成功或失败结果，未导出完成。")
    count, total = len(row['papers']), row['expected']
    if not row['errors'] and total == count == len(catalog):
        row.update(status='complete' if total else 'empty',
                   message=f'{count}/{total} 份已通过清单与磁盘复核' if total else '学校搜索结果为 0 份')
    else:
        row.update(status='partial' if count else 'failed',
                   message=f"归档未完成：已校验 {count}/{total if total is not None else '?'} 份。" + row['errors'][0])
