#!/usr/bin/env python3
# JP AROMATIC Activity Delete/Archive - V3 wrapped-SQL compatible guarded updater
# Python 3.9+. No external packages, no network, no database access.
# Commands:
#   python JP_AROMATIC_Event_Delete_Archive_Adaptive.py --check
#   python JP_AROMATIC_Event_Delete_Archive_Adaptive.py --apply
import argparse
import ast
import difflib
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile

REPLACEMENTS = [
    ('A. 取得活動列表並分離封存', 'project/admin.py',
     '    # 活動管理統一使用 events；不另區分 campaigns。\n    cursor.execute("""\n        SELECT e.*, CONCAT_WS(\'\', u.surname, u.firstname) AS customer_name\n        FROM events e\n        LEFT JOIN users u ON u.id = e.customer_id\n        ORDER BY e.start_date DESC, e.id DESC\n    """)\n    events = cursor.fetchall()\n\n',
     '    # 活動管理統一使用 events。封存活動不再供新訂單選取。\n    cursor.execute("""\n        SELECT e.*, CONCAT_WS(\'\', u.surname, u.firstname) AS customer_name\n        FROM events e\n        LEFT JOIN users u ON u.id = e.customer_id\n        ORDER BY e.start_date DESC, e.id DESC\n    """)\n    all_events = cursor.fetchall()\n    events = [e for e in all_events if not e[\'is_archived\']]\n    archived_events = [e for e in all_events if e[\'is_archived\']]\n\n'),
    ('B. 傳入封存清單至管理頁', 'project/admin.py',
     '        events=events,\n',
     '        events=events,\n        archived_events=archived_events,\n'),
    ('C. 刪除／封存路由與權限', 'project/admin.py',
     '@admin_bp.route(\'/event/<int:event_id>/delete\', methods=[\'POST\'])\n@staff_required\ndef delete_event(event_id):\n    """Delete event"""\n    try:\n        cursor = database.connection.cursor()\n\n        # Get title\n        cursor.execute("SELECT title FROM events WHERE id = %s", (event_id,))\n        res = cursor.fetchone()\n        e_title = res[0] if res else \'Unknown\'\n\n        cursor.execute("DELETE FROM events WHERE id = %s", (event_id,))\n        database.connection.commit()\n        cursor.close()\n\n        # ⭐ LOG ACTIVITY\n        log_activity(\'delete\', \'event\', event_id, {\'title\': e_title})\n\n        flash(\'活動已刪除\', \'success\')\n    except Exception as e:\n        database.connection.rollback()\n        flash(f\'刪除失敗: {str(e)}\', \'error\')\n\n    return redirect(url_for(\'admin.dashboard\', tab=\'events\'))\n\n',
     '@admin_bp.route(\'/event/<int:event_id>/delete\', methods=[\'POST\'])\n@admin_required\ndef delete_event(event_id):\n    """Unlinked events may be deleted; linked events are archived, preserving order history."""\n    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)\n    action = None\n    event_title = None\n    try:\n        # Lock the parent row: a concurrent order adding an FK must wait.\n        cursor.execute(\'SELECT id,title,is_archived FROM events WHERE id=%s FOR UPDATE\', (event_id,))\n        event = cursor.fetchone()\n        if not event:\n            flash(\'活動不存在或已刪除\', \'warning\')\n        elif event[\'is_archived\']:\n            flash(\'這筆活動已封存\', \'info\')\n        else:\n            event_title = event[\'title\']\n            cursor.execute(\'SELECT COUNT(*) AS n FROM order_events WHERE event_id=%s\', (event_id,))\n            linked_orders = cursor.fetchone()[\'n\']\n            if linked_orders:\n                cursor.execute(\'UPDATE events SET is_archived=1 WHERE id=%s\', (event_id,))\n                action = \'archive\'\n            else:\n                cursor.execute(\'DELETE FROM events WHERE id=%s\', (event_id,))\n                if cursor.rowcount != 1:\n                    raise RuntimeError(\'活動刪除未成功，請重新載入後再試\')\n                action = \'delete\'\n            database.connection.commit()\n            flash(\'活動已封存，歷史訂單關聯保留\' if action == \'archive\' else \'活動已永久刪除\', \'success\')\n    except MySQLdb.IntegrityError:\n        database.connection.rollback()\n        current_app.logger.exception(\'Event deletion blocked by database constraint: %s\', event_id)\n        flash(\'活動仍被其他資料參照，未刪除任何資料；請查看 Railway 執行日誌\', \'error\')\n    except Exception:\n        database.connection.rollback()\n        current_app.logger.exception(\'Failed to delete or archive event %s\', event_id)\n        flash(\'活動刪除／封存失敗，請查看 Railway 執行日誌\', \'error\')\n    finally:\n        cursor.close()\n    if action:\n        try:\n            log_activity(action, \'event\', event_id, {\'title\': event_title})\n        except Exception:\n            current_app.logger.exception(\'Could not audit event %s\', event_id)\n    return redirect(url_for(\'admin.dashboard\', tab=\'events\'))\n\n'),
    ('F. 刪除按鈕提示文字', 'project/templates/admin_dashboard.html',
     '            <form method="POST" action="{{ url_for(\'admin.delete_event\', event_id=event.id) }}" class="d-inline"\n              onsubmit="return confirm(\'刪除？\')">\n              <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">\n              <button class="btn btn-sm btn-outline-danger"><i class="bi bi-trash"></i></button>\n            </form>\n',
     '            <form method="POST" action="{{ url_for(\'admin.delete_event\', event_id=event.id) }}" class="d-inline"\n              onsubmit="return confirm(\'確認處理這筆活動？未關聯訂單的活動會永久刪除；已關聯訂單的活動只會封存，保留歷史紀錄。\')">\n              <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">\n              <button type="submit" class="btn btn-sm btn-outline-danger" title="刪除／封存活動"><i class="bi bi-trash"></i></button>\n            </form>\n'),
    ('G. 顯示管理員已封存清單', 'project/templates/admin_dashboard.html',
     '      </tbody>\n    </table>\n  </div>\n\n  <div class="tab-pane fade {% if tab == \'inventory\' %}show active{% endif %}" id="inventory">',
     '      </tbody>\n    </table>\n    {% if archived_events and session.get(\'user\', {}).get(\'role\') == \'admin\' %}\n    <details class="mt-3 mb-2">\n      <summary class="text-muted">已封存活動（{{ archived_events|length }}）</summary>\n      <ul class="list-group mt-2">\n        {% for event in archived_events %}\n        <li class="list-group-item d-flex justify-content-between align-items-center">\n          <span>{{ event.title }}</span><span class="badge bg-secondary">已封存</span>\n        </li>\n        {% endfor %}\n      </ul>\n    </details>\n    {% endif %}\n  </div>\n\n  <div class="tab-pane fade {% if tab == \'inventory\' %}show active{% endif %}" id="inventory">'),

]

FILES = ('project/admin.py', 'project/templates/admin_dashboard.html')
def scoped_event_sql_updates(code):
    """Modify only the two named functions; tolerate wrapped execute() calls."""
    errs = []

    def replace_once(src, old, replacement, label):
        count = src.count(old)
        if count != 1:
            errs.append(f'{label}：預期在指定函式找到 1 次，實際 {count} 次；不修改檔案')
            return src
        return src.replace(old, replacement, 1)

    def locate(source, func):
        matches = list(re.finditer(r'(?m)^def ' + re.escape(func) + r'\([^\n]*\):[ \t]*$', source))
        if len(matches) != 1:
            errs.append(f'找不到唯一的 {func} 函式（找到 {len(matches)} 處）')
            return None
        start = matches[0].start()
        next_definition = re.search(r'(?m)^(?:@admin_bp\.route|def |class )', source[matches[0].end():])
        boundary = matches[0].end() + next_definition.start() if next_definition else len(source)
        return start, boundary

    bounds = locate(code, 'add_order_manual')
    if bounds:
        a, b = bounds
        body = code[a:b]
        before = body
        body = replace_once(
            body,
            "f'SELECT id FROM events WHERE id IN ({placeholders})'",
            "f'SELECT id FROM events WHERE is_archived=0 AND id IN ({placeholders})'",
            'D. 新訂單禁止關聯封存活動',
        )
        if 'if len(cursor.fetchall()) != len(event_ids):' not in before:
            errs.append('D. 找不到原本驗證活動數量的程式')
        code = code[:a] + body + code[b:]

    bounds = locate(code, 'update_order_events')
    if bounds:
        a, b = bounds
        body = code[a:b]
        if 'archived_ids' in body:
            errs.append('E. 已有封存活動處理邏輯，停止以避免重複套用')
        body = replace_once(
            body,
            '        if ids:\n',
            "        # 保留舊訂單已關聯的封存活動，但不允許新加入封存活動。\n"
            "        cursor.execute('''SELECT oe.event_id FROM order_events oe\n"
            "                          JOIN events e ON e.id=oe.event_id\n"
            "                          WHERE oe.order_id=%s AND e.is_archived=1''', (order_id,))\n"
            "        archived_ids = [row['event_id'] for row in cursor.fetchall()]\n"
            "        if ids:\n",
            'E1. 保留舊訂單已封存活動',
        )
        body = replace_once(
            body,
            "f'SELECT id FROM events WHERE id IN ({placeholders})'",
            "f'SELECT id FROM events WHERE is_archived=0 AND id IN ({placeholders})'",
            'E2. 防止新增封存活動',
        )
        body = replace_once(
            body,
            "raise ValueError('活動選項包含已刪除的活動')",
            "raise ValueError('活動選項包含已刪除或已封存的活動')",
            'E3. 調整活動選項錯誤訊息',
        )
        body = replace_once(
            body,
            '        for event_id in ids:\n',
            '        for event_id in archived_ids + ids:\n',
            'E4. 保留封存關聯並儲存有效活動',
        )
        if 'DictCursor' not in body:
            errs.append('E. 原函式不是 DictCursor，封存資料查詢結果可能不相容')
        if "'DELETE FROM order_events WHERE order_id=%s'" not in body:
            errs.append('E. 找不到原本的訂單活動關聯更新 SQL')
        code = code[:a] + body + code[b:]
    return code, errs


def main():
    parser=argparse.ArgumentParser(description='僅修正 JP AROMATIC 活動刪除與封存功能')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='檢查並預覽，不寫入檔案')
    mode.add_argument('--apply', action='store_true', help='所有檢查成功才修改兩個檔案')
    args=parser.parse_args()
    root=Path.cwd()
    if not (root/'.git').exists():
        sys.exit('錯誤：請從 JP-SPA-Web-Application 專案根目錄執行。')
    def git(*argv):
        return subprocess.run(['git', *argv], cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace')
    branch=git('branch','--show-current')
    if branch.returncode or branch.stdout.strip() != 'main':
        sys.exit('錯誤：本修正是 Production main 專用，請先切換至 main。')
    status=git('status','--porcelain','--', *FILES)
    if status.returncode or status.stdout.strip():
        sys.exit('錯誤：目標程式檔案存在未提交的修改，為保護原有內容已停止：\\n'+status.stdout)
    before={}
    after={}
    line_ending={}
    bom={}
    errors=[]
    for filename in FILES:
        path=root/filename
        if not path.is_file():
            errors.append('找不到 '+filename)
            continue
        raw=path.read_bytes()
        bom[filename]=raw.startswith(b'\xef\xbb\xbf')
        if bom[filename]:
            raw=raw[3:]
        line_ending[filename]='\r\n' if b'\r\n' in raw else '\n'
        if b'\r\n' in raw and raw.count(b'\n') != raw.count(b'\r\n'):
            errors.append('發現混合換行格式，已停止：'+filename)
        before[filename]=raw.decode('utf-8')
        after[filename]=before[filename]
    if errors:
        sys.exit('檢查未通過：\\n'+'\\n'.join(errors))
    for name, filename, old, new in REPLACEMENTS:
        old=old.replace('\n',line_ending[filename])
        new=new.replace('\n',line_ending[filename])
        count=after[filename].count(old)
        if count != 1:
            errors.append(f'{name}：預期原始片段出現 1 次，實際為 {count} 次；不自動猜測位置')
        else:
            after[filename]=after[filename].replace(old, new, 1)
    # D/E: compare exact SQL literal text within functions, not execute() wrapping.
    normalized = after['project/admin.py'].replace('\r\n', '\n')
    normalized, scoped_errors = scoped_event_sql_updates(normalized)
    errors.extend(scoped_errors)
    after['project/admin.py'] = normalized.replace('\n', line_ending['project/admin.py'])
    if not errors:
        try:
            ast.parse(after['project/admin.py'])
        except SyntaxError as exc:
            errors.append(f'Python 語法未通過：{exc}')
    if errors:
        print('修正已中止，尚未寫入任何檔案：',file=sys.stderr)
        for msg in errors:
            print(' - '+msg,file=sys.stderr)
        sys.exit(2)
    diff=[]
    for filename in FILES:
        diff.extend(difflib.unified_diff(before[filename].splitlines(keepends=True), after[filename].splitlines(keepends=True), fromfile='a/'+filename, tofile='b/'+filename, n=3))
    print('所有 7 類修改及 Python 語法檢查通過。')
    print('僅修改 project/admin.py 和 project/templates/admin_dashboard.html')
    print('變更預覽：')
    for line in diff:
        print(line, end='')
    if args.check:
        print('\\n[CHECK ONLY] 未修改任何檔案。')
        return
    # All checks and preview completed before modifying either file.
    temporary=[]
    try:
        for filename in FILES:
            target=root/filename
            fd, tmppath=tempfile.mkstemp(prefix='.event-archive-', suffix='.tmp', dir=target.parent)
            os.close(fd)
            tmp=Path(tmppath)
            tmp.write_bytes((b'\xef\xbb\xbf' if bom[filename] else b'') + after[filename].encode('utf-8'))
            temporary.append((tmp,target))
        for tmp,target in temporary:
            os.replace(tmp,target)
        print('\\n[APPLIED] 已修改 2 個檔案。下一步請檢查 git diff，不要直接跳過驗證。')
    finally:
        for tmp,_ in temporary:
            if tmp.exists():
                tmp.unlink()

if __name__=='__main__':
    main()
