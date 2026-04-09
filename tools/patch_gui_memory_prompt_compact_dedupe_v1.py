#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import difflib
from datetime import datetime
from pathlib import Path
import textwrap


SCRIPT_NAME = "patch_gui_memory_prompt_compact_dedupe_v1"


def print_hr():
    print("=" * 96)


def print_header():
    print_hr()
    print(SCRIPT_NAME)
    print_hr()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_backup(root: Path, target: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    rel = target.relative_to(root)
    backup_path = backup_root / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


def compile_check(target: Path, new_text: str) -> None:
    compile(new_text, str(target), "exec")


def unified_diff(before: str, after: str, fromfile: str, tofile: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
            n=3,
        )
    )


def replace_between(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement_block: str,
) -> tuple[str, int, int]:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"anchor_not_found:start:{start_marker}")

    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"anchor_not_found:end:{end_marker}")

    new_text = text[:start] + replacement_block + text[end:]
    return new_text, start, end


def build_memory_block_replacement() -> str:
    return textwrap.dedent(
        """
        def _sanhua_gui_mem_key(_text):
            _text = str(_text or '').strip().lower()
            if not _text:
                return ''
            return ' '.join(_text.split())


        def _sanhua_gui_mem_compact_text(_text, _limit=160):
            _text = str(_text or '').replace('\\u3000', ' ').strip()
            if not _text:
                return ''

            _text = '\\n'.join(_line.strip() for _line in _text.splitlines() if _line.strip())
            _text = ' '.join(_text.split())

            try:
                _limit = int(_limit or 0)
            except Exception:
                _limit = 0

            if _limit > 0 and len(_text) > _limit:
                _text = _text[: max(_limit - 1, 1)].rstrip() + '…'

            return _text


        def _sanhua_gui_mem_is_polluted_text(_text):
            _text = str(_text or '').strip()
            if not _text:
                return False

            _checker = globals().get('_sanhua_gui_display_is_polluted')
            if callable(_checker):
                try:
                    if _checker(_text):
                        return True
                except Exception:
                    pass

            _markers = (
                '请把下面这些系统记忆当作高优先级参考事实',
                '下面是与当前问题强相关的记忆摘要',
                '当前用户问题：',
                '用户问题：',
                '【稳定身份记忆】',
                '【最近会话】',
                '【相关记忆命中】',
                '【用户画像】',
                '【最近用户消息】',
                '【相关记忆摘要】',
                'FAKE_AICORE_REPLY::',
            )
            return any(_m in _text for _m in _markers)


        def _sanhua_gui_mem_push_unique(_arr, _seen, _text, _limit=160, _max_items=None):
            _text = _sanhua_gui_mem_compact_text(_text, _limit=_limit)
            if not _text:
                return False

            if _sanhua_gui_mem_is_polluted_text(_text):
                return False

            _key = _sanhua_gui_mem_key(_text)
            if not _key or _key in _seen:
                return False

            _arr.append(_text)
            _seen.add(_key)

            if _max_items is not None:
                try:
                    _max_items = int(_max_items)
                except Exception:
                    _max_items = None

                if _max_items is not None and _max_items >= 0 and len(_arr) > _max_items:
                    del _arr[_max_items:]

            return True


        def _sanhua_gui_mem_collect_context(_aicore, _user_text, _limit=5):
            _query = _sanhua_gui_mem_compact_text(_user_text, _limit=120)
            _payload = {
                'identity': {},
                'recent_messages': [],
                'matches': [],
            }

            if not _query:
                return _payload

            try:
                _limit = max(int(_limit or 5), 5)
            except Exception:
                _limit = 5

            _query_key = _sanhua_gui_mem_key(_query)

            # 1) recall 结果：去重、去污染、去当前问题回声
            _recall = _sanhua_gui_mem_execute(
                _aicore,
                'memory.recall',
                query=_query,
                limit=max(_limit, 8),
            )

            _match_seen = set()
            if isinstance(_recall, dict):
                _results = _recall.get('results') or _recall.get('items') or []
                for _item in _results:
                    _norm = _sanhua_gui_mem_normalize_match(_item)
                    _norm = _sanhua_gui_mem_compact_text(_norm, _limit=96)
                    if not _norm:
                        continue
                    if _sanhua_gui_mem_key(_norm) == _query_key:
                        continue
                    _sanhua_gui_mem_push_unique(
                        _payload['matches'],
                        _match_seen,
                        _norm,
                        _limit=96,
                        _max_items=3,
                    )

            # 2) snapshot：只在身份/回忆类问题时取，避免每次都塞太胖
            _need_snapshot = (
                any(_hint in _query for _hint in _SANHUA_GUI_MEMORY_QUERY_HINTS)
                or '回忆' in _query
                or '刚才' in _query
                or '记住' in _query
            )

            if not _need_snapshot:
                return _payload

            _snapshot = _sanhua_gui_mem_execute(_aicore, 'memory.snapshot')
            if not isinstance(_snapshot, dict):
                return _payload

            _snap = _snapshot.get('snapshot') or {}
            _persona = ((_snap.get('persona') or {}).get('user_profile') or {})
            _session = ((_snap.get('session_cache') or {}).get('active_session') or {})
            _recent = _session.get('recent_messages') or []

            # 2.1) identity：白名单压缩，避免 stable_facts 全灌进去
            _alias_seen = set()
            _aliases = []
            for _x in (_persona.get('aliases') or []):
                _x = _sanhua_gui_mem_compact_text(_x, _limit=24)
                if not _x:
                    continue
                _k = _sanhua_gui_mem_key(_x)
                if not _k or _k in _alias_seen:
                    continue
                _alias_seen.add(_k)
                _aliases.append(_x)
                if len(_aliases) >= 3:
                    break

            _focus_seen = set()
            _project_focus = []
            for _x in (_persona.get('project_focus') or []):
                _x = _sanhua_gui_mem_compact_text(_x, _limit=32)
                if not _x:
                    continue
                _k = _sanhua_gui_mem_key(_x)
                if not _k or _k in _focus_seen:
                    continue
                _focus_seen.add(_k)
                _project_focus.append(_x)
                if len(_project_focus) >= 4:
                    break

            _stable_src = _persona.get('stable_facts') or {}
            _stable_facts = {}
            for _k in (
                'identity.name',
                'system.primary_project',
                'response.preference',
                'memory_architecture_focus',
            ):
                _v = _sanhua_gui_mem_compact_text(_stable_src.get(_k), _limit=80)
                if _v:
                    _stable_facts[_k] = _v

            _identity_candidate = {
                'name': _sanhua_gui_mem_compact_text(_persona.get('name'), _limit=24),
                'aliases': _aliases,
                'notes': _sanhua_gui_mem_compact_text(_persona.get('notes'), _limit=120),
                'project_focus': _project_focus,
                'stable_facts': _stable_facts,
            }

            _has_identity = any([
                str(_identity_candidate.get('name') or '').strip(),
                any(str(x).strip() for x in (_identity_candidate.get('aliases') or [])),
                str(_identity_candidate.get('notes') or '').strip(),
                any(str(x).strip() for x in (_identity_candidate.get('project_focus') or [])),
                any(str(v).strip() for v in (_identity_candidate.get('stable_facts') or {}).values()),
            ])
            if _has_identity:
                _payload['identity'] = _identity_candidate

            # 2.2) recent：只保留最近用户消息，去重去污染，避免 assistant echo 污染继续滚胖
            _recent_seen = set()
            _recent_rows = []
            for _m in _recent[-12:]:
                if not isinstance(_m, dict):
                    continue

                _role = str(_m.get('role') or '').strip() or 'unknown'
                _content = _sanhua_gui_mem_compact_text(_m.get('content'), _limit=120)

                if _role != 'user':
                    continue
                if not _content:
                    continue
                if _sanhua_gui_mem_is_polluted_text(_content):
                    continue
                if _sanhua_gui_mem_key(_content) == _query_key:
                    continue

                _row_key = f'{_role}:{_sanhua_gui_mem_key(_content)}'
                if _row_key in _recent_seen:
                    continue

                _recent_seen.add(_row_key)
                _recent_rows.append({'role': 'user', 'content': _content})

            _payload['recent_messages'] = _recent_rows[-4:]
            return _payload


        def _sanhua_gui_mem_build_prompt(_user_text, _ctx):
            _user_text = str(_user_text or '').strip()
            if not _user_text:
                return _user_text

            if not isinstance(_ctx, dict):
                return _user_text

            _sections = []

            # A) 用户画像：极简
            _identity = _ctx.get('identity') or {}
            if _identity:
                _lines = []
                _name = _sanhua_gui_mem_compact_text(_identity.get('name'), _limit=24)
                _aliases = [str(x).strip() for x in (_identity.get('aliases') or []) if str(x).strip()]
                _project_focus = [str(x).strip() for x in (_identity.get('project_focus') or []) if str(x).strip()]
                _notes = _sanhua_gui_mem_compact_text(_identity.get('notes'), _limit=96)
                _stable_facts = _identity.get('stable_facts') or {}

                if _name:
                    _lines.append(f'- 用户名：{_name}')
                if _aliases:
                    _lines.append(f"- 别名：{', '.join(_aliases[:3])}")
                if _project_focus:
                    _lines.append(f"- 项目重点：{', '.join(_project_focus[:4])}")

                _primary_project = _sanhua_gui_mem_compact_text(
                    _stable_facts.get('system.primary_project'),
                    _limit=40,
                )
                if _primary_project:
                    _lines.append(f'- 核心项目：{_primary_project}')

                _preference = _sanhua_gui_mem_compact_text(
                    _stable_facts.get('response.preference'),
                    _limit=60,
                )
                if _preference:
                    _lines.append(f'- 回复偏好：{_preference}')

                if _notes:
                    _lines.append(f'- 备注：{_notes}')

                if _lines:
                    _sections.append('【用户画像】\\n' + '\\n'.join(_lines))

            # B) 最近用户消息：只放用户话术，限制 4 条
            _recent_lines = []
            _recent_seen = set()
            for _item in (_ctx.get('recent_messages') or [])[-4:]:
                if not isinstance(_item, dict):
                    continue
                _content = _sanhua_gui_mem_compact_text(_item.get('content'), _limit=88)
                if not _content:
                    continue
                _k = _sanhua_gui_mem_key(_content)
                if not _k or _k in _recent_seen:
                    continue
                _recent_seen.add(_k)
                _recent_lines.append(f'- {_content}')

            if _recent_lines:
                _sections.append('【最近用户消息】\\n' + '\\n'.join(_recent_lines))

            # C) 相关记忆摘要：去掉与 recent 重复的内容
            _match_lines = []
            _match_seen = set(_recent_seen)
            _user_key = _sanhua_gui_mem_key(_user_text)
            for _text in (_ctx.get('matches') or [])[:6]:
                _text = _sanhua_gui_mem_compact_text(_text, _limit=88)
                if not _text:
                    continue
                if _sanhua_gui_mem_is_polluted_text(_text):
                    continue
                _k = _sanhua_gui_mem_key(_text)
                if not _k or _k == _user_key or _k in _match_seen:
                    continue
                _match_seen.add(_k)
                _match_lines.append(f'- {_text}')
                if len(_match_lines) >= 3:
                    break

            if _match_lines:
                _sections.append('【相关记忆摘要】\\n' + '\\n'.join(_match_lines))

            if not _sections:
                return _user_text

            _memory_block = '\\n\\n'.join(_sections).strip()
            return (
                '下面是与当前问题强相关的记忆摘要，仅在相关时参考；'
                '不要逐字复述摘要，也不要把摘要原样输出给用户。\\n'
                '请直接用自然中文给出最终答复。\\n\\n'
                f'{_memory_block}\\n\\n'
                f'用户问题：\\n{_user_text}'
            )


        """
    ).lstrip()


def build_display_pollution_replacement() -> str:
    return textwrap.dedent(
        """
        def _sanhua_gui_display_is_polluted(_text):
            _text = str(_text or '').strip()
            if not _text:
                return False

            _markers = (
                '请把下面这些系统记忆当作高优先级参考事实',
                '下面是与当前问题强相关的记忆摘要',
                '当前用户问题：',
                '用户问题：',
                '【稳定身份记忆】',
                '【最近会话】',
                '【相关记忆命中】',
                '【用户画像】',
                '【最近用户消息】',
                '【相关记忆摘要】',
                'FAKE_AICORE_REPLY::',
            )
            return any(_m in _text for _m in _markers)


        """
    ).lstrip()


def patch_file(root: Path, apply: bool) -> int:
    target = root / "entry" / "gui_entry" / "gui_main.py"

    print_header()
    print(f"root   : {root}")
    print(f"apply  : {apply}")
    print(f"target : {target}")

    if not target.exists():
        print("[ERROR] target_not_found")
        return 1

    before = read_text(target)
    after = before

    # 1) memory compact + dedupe block
    memory_start = "def _sanhua_gui_mem_collect_context("
    memory_end = "def _sanhua_gui_mem_append_chat("
    memory_block = build_memory_block_replacement()
    after, memory_s, memory_e = replace_between(after, memory_start, memory_end, memory_block)

    # 2) display pollution markers upgrade
    display_start = "def _sanhua_gui_display_is_polluted("
    display_end = "def _sanhua_gui_local_memory_identity_reply("
    display_block = build_display_pollution_replacement()
    after, display_s, display_e = replace_between(after, display_start, display_end, display_block)

    try:
        compile_check(target, after)
    except Exception as e:
        print(f"[ERROR] 语法检查失败: {e}")
        return 1

    diff = unified_diff(
        before,
        after,
        f"--- {target} (before)",
        f"+++ {target} (after)",
    )

    print(f"[INFO] memory_range  : chars[{memory_s}:{memory_e}] -> replaced")
    print(f"[INFO] display_range : chars[{display_s}:{display_e}] -> replaced")

    if diff.strip():
        print("[DIFF PREVIEW]")
        print(diff)
    else:
        print("[INFO] no_diff")

    if not apply:
        print("[PREVIEW] 补丁可应用，且语法通过")
        print_hr()
        return 0

    backup = make_backup(root, target)
    write_text(target, after)

    print(f"[BACKUP] {backup}")
    print(f"[PATCHED] {target}")
    print("[OK] 语法检查通过")
    print_hr()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="项目根目录")
    parser.add_argument("--apply", action="store_true", help="实际写入补丁")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    return patch_file(root, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
