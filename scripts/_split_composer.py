"""Extract PATTERNS + COMPOUND_PATTERNS from git original"""
import subprocess

r = subprocess.run(
    ['git', 'show', 'HEAD:src/language_system/sentence_composer.py'],
    capture_output=True, text=True, encoding='utf-8'
)
lines = r.stdout.splitlines()
print(f'Original: {len(lines)} lines')

# PATTERNS data: lines 40-849 (1-indexed)
# Line 40: "PATTERNS: List[Dict] = []"
# Line 64: first "PATTERNS += ["
# Line 849: last "]" of COMPOUND_PATTERNS data
PAT_START = 40
DATA_END = 849

data_lines = lines[PAT_START-1:DATA_END]  # 0-indexed

# Build patterns file
docstring = [
    '"""Sentence Composer Patterns — PATTERNS + COMPOUND_PATTERNS template library.\n',
    '\n',
    'Extracted from sentence_composer.py.\n',
    '\n',
    'Submodules:\n',
    '    sentence_composer_schema.py   — hyperparameters + math helpers\n',
    '    sentence_composer_patterns.py — PATTERNS + COMPOUND_PATTERNS (this file)\n',
    '    sentence_composer_helpers.py  — standalone math helpers\n',
    '    sentence_composer.py         — core composition logic\n',
    '"""\n',
    '\n',
    'from typing import Dict, List\n',
    '\n',
]

with open('src/language_system/sentence_composer_patterns.py', 'w', encoding='utf-8') as f:
    f.writelines(docstring + data_lines + ['\n'])
print(f'Wrote {len(docstring) + len(data_lines) + 1} lines to patterns file')

# Update sentence_composer.py: add COMPOUND_PATTERNS import
src_lines = open('src/language_system/sentence_composer.py', encoding='utf-8').readlines()
new_lines = []
for l in src_lines:
    new_lines.append(l)
    if 'from .sentence_composer_patterns import PATTERNS' in l:
        new_lines.append('from .sentence_composer_patterns import COMPOUND_PATTERNS\n')

with open('src/language_system/sentence_composer.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

# Verify
for f, limit in [
    ('src/language_system/sentence_composer.py', 400),
    ('src/language_system/sentence_composer_patterns.py', 400),
    ('src/language_system/sentence_composer_helpers.py', 400),
]:
    n = len(open(f, encoding='utf-8').readlines())
    print(f'{f}: {n} lines', ' OK' if n < limit else ' OVER')

# Compile
for f in [
    'src/language_system/sentence_composer.py',
    'src/language_system/sentence_composer_patterns.py',
    'src/language_system/sentence_composer_helpers.py',
]:
    r2 = subprocess.run(['python', '-m', 'py_compile', f], capture_output=True)
    ok = 'OK' if r2.returncode == 0 else f'FAIL: {r2.stderr.decode()[:80]}'
    print(f'py_compile {f}: {ok}')
