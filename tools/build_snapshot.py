#!/usr/bin/env python3
"""Build the reviewed candidate using an explicit file allowlist."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _workbuddy_files(checked):
    # The marketplace accepts files only at ZIP root or one immediate folder.
    included = [(name, data) for name, data in checked
                if not name.startswith(('tests/', 'tools/', 'examples/preview/'))
                and name not in ('SNAPSHOT_FILES.txt', '.gitignore')]
    mapping = {name: ('examples/' + Path(name).name if name.startswith('examples/') else name)
               for name, _ in included}
    if len(set(mapping.values())) != len(mapping):
        raise ValueError('Flattened release paths collide')
    rewritten = []
    for name, data in included:
        if Path(name).suffix in ('.md', '.json'):
            text = data.decode('utf-8')
            for old, new in sorted(mapping.items(), key=lambda x: -len(x[0])):
                if old != new:
                    text = text.replace(old, new)
                    if old.startswith('examples/assets/'):
                        text = text.replace(old.removeprefix('examples/'), Path(new).name)
            if name == 'README.md':
                text += '\n## 上传包布局\n\nSKILL.md 位于 ZIP 根目录；文件最多一层子目录。示例已压平到 examples/ 并改写路径。tests/、tools/ 和历史 preview 仅保留于开发源码中，本文相关开发测试命令须在源码仓库运行。上传包文件映射见 RELEASE_FILES.json。\n'
            data = text.encode('utf-8')
        new = mapping[name]
        if len(Path(new).parts) > 2:
            raise ValueError(f'WorkBuddy directory depth exceeded: {new}')
        rewritten.append((new, data))
    manifest = {'layout': 'workbuddy-root-plus-one-folder', 'files': [
        {'source': name, 'archive': mapping[name],
         'source_sha256': hashlib.sha256(data).hexdigest(),
         'archive_sha256': hashlib.sha256(dict(rewritten)[mapping[name]]).hexdigest()}
        for name, data in included]}
    rewritten.append(('RELEASE_FILES.json', json.dumps(manifest, ensure_ascii=False, indent=2).encode()))
    return rewritten


def _generic_files(checked):
    included = [(name, data) for name, data in checked
                if not name.startswith(('tests/', 'tools/', 'examples/preview/'))
                and name not in ('SNAPSHOT_FILES.txt', '.gitignore')]
    result = []
    records = []
    for name, original in included:
        data = original
        if name == 'SKILL.md':
            _, header, body = data.decode().split('---', 2)
            values = dict(line.split(':', 1) for line in header.splitlines() if ':' in line)
            values = {k: v.strip() for k, v in values.items()}
            # Standard Skill frontmatter; host-specific display fields become metadata.
            header = ('---\nname: ' + values['name'] + '\ndescription: '
                      + json.dumps(values['description_zh'], ensure_ascii=False)
                      + '\nmetadata:\n  version: ' + json.dumps(values['version'])
                      + '\n  author: ' + json.dumps(values['author']) + '\n---')
            body = body.replace('WorkBuddy Skill', 'Agent Skill').replace('WorkBuddy 资源与执行入口', '资源与执行入口')
            body = body.replace('@references/', 'references/')
            data = (header + body).encode()
        elif name == 'README.md':
            text = data.decode().replace('WorkBuddy / Agent Skill', '通用 Agent Skill')
            text += '\n## 通用 Agent 发行包\n\n本包使用标准 SKILL.md 元数据，保留正常目录结构，不依赖 WorkBuddy。请将解压后的 quick-pass-exam 文件夹放入宿主支持的 Skills 目录，并按宿主说明启用。需要本地 Python/命令执行与文件访问能力。开发测试、构建工具和历史预览保留于源码仓库；本文开发测试命令应在源码仓库运行。具体宿主安装界面未逐一验证。\n'
            data = text.encode()
        elif name == 'provenance.json':
            obj = json.loads(data)
            obj['release']['distribution'] = 'generic-agent-skill'
            data = (json.dumps(obj, ensure_ascii=False, indent=2) + '\n').encode()
        result.append((name, data))
        records.append({'source': name, 'archive': name,
                        'source_sha256': hashlib.sha256(original).hexdigest(),
                        'archive_sha256': hashlib.sha256(data).hexdigest()})
    result.append(('RELEASE_FILES.json', json.dumps({'layout': 'generic-agent-skill', 'files': records}, ensure_ascii=False, indent=2).encode()))
    return [('quick-pass-exam/' + name, data) for name, data in result]


def build(output: Path, *, layout: str = 'workbuddy') -> None:
    names = [line.strip() for line in (ROOT / 'SNAPSHOT_FILES.txt').read_text().splitlines()
             if line.strip() and not line.startswith('#')]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate allowlist entries')
    checked = []
    for name in names:
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts or '__pycache__' in rel.parts:
            raise ValueError(f'Unsafe snapshot path: {name}')
        file = ROOT / rel
        if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(ROOT):
            raise ValueError(f'Missing or unsafe file: {name}')
        checked.append((name, file.read_bytes()))
    if layout == 'workbuddy':
        checked = _workbuddy_files(checked)
    elif layout == 'generic':
        checked = _generic_files(checked)
    elif layout == 'source':
        checked = [('quick-pass-exam/' + name, data) for name, data in checked]
    else:
        raise ValueError('Unknown layout')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as target:
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in checked:
                archive.writestr(_zip_info(name), content)
    print(f'{output.name}: {len(checked)} files; sha256={hashlib.sha256(output.read_bytes()).hexdigest()}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--layout', choices=['workbuddy', 'generic', 'source'], default='workbuddy')
    args = parser.parse_args()
    build(args.output, layout=args.layout)
