"""Independent SBX-28 acceptance probes; no product implementation changes."""

import csv
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from todo_lite import storage
from todo_lite.cli import main

ROOT = Path(__file__).resolve().parents[1]


def invoke(db, *args):
    # Keep bytes: text=True would normalize CR and hide CSV data loss.
    return subprocess.run(
        [sys.executable, '-m', 'todo_lite', '--db', str(db), *args],
        cwd=ROOT, capture_output=True, check=False,
    )


@pytest.mark.parametrize('destination', ['stdout', 'file'])
@pytest.mark.parametrize('text', [
    '中文,"引号"\n第二行', 'a\r\nb', 'a\rb', 'a\r', '\rb',
    'emoji 🎉\t空格', '',
])
def test_csv_byte_preserving_roundtrip(tmp_path, destination, text):
    db = tmp_path / 'db.json'
    storage.save(db, [{'text': text, 'done': False}])
    args = ['export', '--format', 'csv']
    output = tmp_path / 'export.csv'
    if destination == 'file':
        args += ['--output', str(output)]
    result = invoke(db, *args)
    assert result.returncode == 0, result.stderr
    payload = output.read_bytes() if destination == 'file' else result.stdout
    rows = list(csv.reader(io.StringIO(payload.decode('utf-8'), newline='')))
    assert rows == [['id', 'text', 'done'], ['1', text, 'false']]


@pytest.mark.parametrize('needle,expected', [
    ('STRASSE', '2. [ ] Straße'), ('σ', '3. [x] ςΣ'),
    ('', '1. [ ] 无关\n2. [ ] Straße\n3. [x] ςΣ\n4. [ ] --x.*'),
    ('--x.*', '4. [ ] --x.*'), ('不存在', '没有符合条件的待办'),
])
def test_unicode_empty_and_literal_search(tmp_path, needle, expected):
    db = tmp_path / 'db.json'
    storage.save(db, [
        {'text': '无关', 'done': False}, {'text': 'Straße'},
        {'text': 'ςΣ', 'done': True}, {'text': '--x.*', 'done': False},
    ])
    before = db.read_bytes()
    result = invoke(db, 'list', '--search=' + needle)
    assert (result.returncode, result.stdout.decode(), result.stderr) == (0, expected + '\n', b'')
    assert db.read_bytes() == before


def test_filtered_ids_drive_mutations_and_export_all(tmp_path, capsys):
    db = tmp_path / 'db.json'
    storage.save(db, [
        {'text': 'unrelated', 'done': False},
        {'text': 'MATCH first', 'done': True},
        {'text': 'match second', 'done': False},
    ])
    before = db.read_bytes()
    result = invoke(db, 'list', '--status', 'open', '--search', 'MaTcH')
    assert (result.returncode, result.stdout) == (0, b'3. [ ] match second\n')
    assert db.read_bytes() == before
    index = result.stdout.split(b'.', 1)[0].decode()
    assert main(['--db', str(db), 'done', index]) == 0
    assert main(['--db', str(db), 'remove', '2']) == 0
    capsys.readouterr()
    exported = invoke(db, 'export', '--format', 'json')
    assert exported.returncode == 0
    assert json.loads(exported.stdout) == [
        {'id': 1, 'text': 'unrelated', 'done': False},
        {'id': 2, 'text': 'match second', 'done': True},
    ]
    assert invoke(db, 'list', '--status', 'done').stdout == b'2. [x] match second\n'


@pytest.mark.parametrize('args', [
    ['export'], ['export', '--format', 'yaml'], ['export', '--format'],
    ['list', '--status', 'closed'], ['list', '--status'], ['list', '--search'],
    ['export', '--format', 'json', '--status', 'open'],
])
def test_invalid_cli_does_not_touch_files(tmp_path, args):
    db = tmp_path / 'db.json'
    storage.save(db, [{'text': '保留', 'done': False}])
    before = db.read_bytes()
    result = invoke(db, *args)
    assert result.returncode == 2
    assert result.stdout == b''
    assert result.stderr
    assert db.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ['db.json']


@pytest.mark.parametrize('exists', [False, True])
def test_empty_filtered_list_and_exports(tmp_path, exists):
    db = tmp_path / 'db.json'
    if exists:
        storage.save(db, [])
    for args in [('list', '--search', ''), ('list', '--status', 'done')]:
        result = invoke(db, *args)
        assert (result.returncode, result.stdout.decode()) == (0, '没有符合条件的待办\n')
    assert invoke(db, 'export', '--format', 'json').stdout == b'[]\n'
    assert invoke(db, 'export', '--format', 'csv').stdout == b'id,text,done\n'
    assert db.exists() == exists
