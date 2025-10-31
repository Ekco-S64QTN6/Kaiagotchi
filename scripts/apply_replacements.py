import argparse
import re
from pathlib import Path
from difflib import unified_diff

ROOT = Path(__file__).resolve().parents[1] / "kaiagotchi"
PATTERNS = [
    # pattern, replacement, description
    (re.compile(r'(?m)^[ \t]*from\s+pwnagotchi\.([A-Za-z0-9_\.]+)\s+import\s+'), r'from .\1 import ', 'from pwnagotchi.module -> from .module'),
    (re.compile(r'(?m)^[ \t]*from\s+pwnagotchi\s+import\s+'), r'from . import ', 'from pwnagotchi import -> from . import'),
    (re.compile(r'(?m)^[ \t]*import\s+pwnagotchi\.([A-Za-z0-9_]+)(\s+as\s+[A-Za-z0-9_]+)?'), r'from . import \1\2', 'import pwnagotchi.module -> from . import module'),
    (re.compile(r'/etc/pwnagotchi'), r'/etc/kaiagotchi', '/etc path'),
    (re.compile(r'service pwnagotchi'), r'service kaiagotchi', 'service name'),
    (re.compile(r'\bpwnagotchi\b'), r'kaiagotchi', 'generic token'),
]

EXTS = {'.py', '.sh', '.service', '.toml', '.md', '.html'}

def files_to_scan():
    for p in ROOT.rglob('*'):
        if p.is_file() and p.suffix in EXTS:
            yield p

def process_file(path: Path, apply: bool):
    text = path.read_text(encoding='utf-8', errors='replace')
    new = text
    for pat, repl, _desc in PATTERNS:
        new = pat.sub(repl, new)
    if new == text:
        return False, None
    diff = '\n'.join(unified_diff(text.splitlines(), new.splitlines(), fromfile=str(path)+'.orig', tofile=str(path), lineterm=''))
    if apply:
        bak = path.with_suffix(path.suffix + '.bak') if not str(path).endswith('.bak') else path.with_suffix(path.suffix + '.bak2')
        path.write_text(new, encoding='utf-8')
        bak.write_text(text, encoding='utf-8')
        return True, diff
    return True, diff

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='Apply changes (creates .bak files). Default: preview only.')
    args = ap.parse_args()
    any_changed = False
    for f in files_to_scan():
        ok, diff = process_file(f, args.apply)
        if ok:
            any_changed = True
            print(f'== {f} ==')
            print(diff or '(no textual diff)')
            print()
    if not any_changed:
        print('No matches found or no replacements necessary.')

if __name__ == '__main__':
    main()