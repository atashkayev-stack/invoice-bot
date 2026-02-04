#!/usr/bin/env python3
"""Правильный анализатор импортов"""
import os, re
from pathlib import Path


def find_imports(file_path):
    """Находит импорты включая from .module"""
    imports = set()
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                # from .database_v1 import X
                # from src.database_v1 import X
                match = re.search(r'from\s+[.\w]+?([\w_]+)\s+import', line)
                if match:
                    imports.add(match.group(1))

                # import database_v1
                match = re.search(r'^import\s+([\w_]+)', line.strip())
                if match:
                    imports.add(match.group(1))
    except:
        pass
    return imports


project_dir = "."
py_files = [f for f in Path(project_dir).rglob('*.py') if 'venv' not in str(f)]

src_modules = {
    f.stem: str(f)
    for f in py_files if 'src' in str(f) or f.parent.name == '.'
}

print("📦 Модули:")
for name in sorted(src_modules.keys()):
    print(f"  {name}.py")

print("\n🔍 Используются в:")
usage = {m: [] for m in src_modules}

for py_file in py_files:
    imports = find_imports(py_file)
    for imp in imports:
        if imp in src_modules:
            usage[imp].append(py_file.stem)

for module in sorted(usage.keys()):
    users = list(set(usage[module]))
    if users:
        print(f"\n✅ {module}.py:")
        for u in sorted(users):
            print(f"    ← {u}.py")
    else:
        print(f"\n❌ {module}.py (не используется)")
