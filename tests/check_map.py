#!/usr/bin/env python3
"""PROJECT_MAP.md gate - run from anywhere; no Qt, no tablet.

The map lists, per source file, one bullet per chunk marker:

    - **chunk: `name`** — what it is, who calls it.

Markers are `# ── chunk: <name>` (`// ── chunk:` in QML) above every top-level
def, class, bash function and script mode, plus a few hand-placed block
markers. Names before the bullet's first " — " count; backticks in the prose
after it are mentions, not documentation. Several chunks may share a bullet
(two or three bold names separated by slashes).

Checks: every marker has a bullet in its file's section; every bullet names a
marker, unless the bullet is tagged *(public copy only)* or *(personal copy
only)*; a marker above a def / class / bash function / case mode carries that
thing's name (a mis-named marker is a stale one); markers are unique within a
file; every source file has a "### `file`" section and every section names a
file (a name ending in "/" is a directory) - a HEADING carrying the same
*(… copy only)* tag may name a file the other copy has and this one has not;
bullets stay short: 200 characters each, 120 on average. Exit 0 = clean.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = os.path.join(ROOT, "PROJECT_MAP.md")
EXTS = (".py", ".sh", ".qml")
MARKER = re.compile(r"^\s*(?:#|//) ── chunk: (\S+)\s*$")
PY_DEF = re.compile(r"^\s*(?:def|class)\s+(\w+)")
SH_FN = re.compile(r"^(\w+)\(\)\s*\{")
SH_CASE = re.compile(r"^(\w+|\*)\)")
HEADING = re.compile(r"^### `([^`]+)`")
BULLET = re.compile(r"^- \*\*chunk: ")
NAME = re.compile(r"`([^`]+)`")
MAX_BULLET, MAX_MEAN = 200, 120


def sources():
    return sorted(f for f in os.listdir(ROOT) if f.endswith(EXTS) and os.path.isfile(os.path.join(ROOT, f)))


def markers_in(path):
    """[(name, line number, name the next code line declares or None)]"""
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    found = []
    for i, line in enumerate(lines):
        m = MARKER.match(line)
        if not m:
            continue
        declared = None
        for nxt in lines[i + 1:]:
            s = nxt.strip()
            if not s or s.startswith("#") or s.startswith("//"):
                continue
            d = PY_DEF.match(nxt) if path.endswith(".py") else None
            if d:
                declared = d.group(1)
            elif path.endswith(".sh"):
                d = SH_FN.match(nxt) or SH_CASE.match(nxt)
                if d:
                    declared = d.group(1)
            break
        found.append((m.group(1), i + 1, declared))
    return found


def parse_map():
    """({section: [(names in the bullet, exempt, bullet length)]}, {section tagged
    *(… copy only)*}), in map order."""
    sections, only, current = {}, set(), None
    with open(MAP, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            h = HEADING.match(line)
            if h:
                current = h.group(1)
                sections.setdefault(current, [])
                if "copy only)*" in line:
                    only.add(current)
                continue
            if current is None or not BULLET.match(line):
                continue
            head = line.split(" — ", 1)[0]
            names = NAME.findall(head)
            exempt = "copy only)*" in line
            sections[current].append((names, exempt, len(line)))
    return sections, only


def main():
    problems = []
    sections, only = parse_map()
    files = sources()
    for name in sections:
        target = os.path.join(ROOT, name)
        if name in only:                      # a file the other copy has: install.sh, say
            continue
        if not (os.path.isdir(target) if name.endswith("/") else os.path.isfile(target)):
            problems.append(f"map: section `{name}` names nothing that exists")
    lengths = []
    total = 0
    for fname in files:
        marks = markers_in(os.path.join(ROOT, fname))
        total += len(marks)
        if fname not in sections:
            problems.append(f"{fname}: no `### \\`{fname}\\`` section in the map")
            continue
        seen = set()
        for name, lineno, declared in marks:
            if name in seen:
                problems.append(f"{fname}:{lineno}: marker `{name}` appears twice in this file")
            seen.add(name)
            if declared not in (None, "*") and declared != name:
                problems.append(f"{fname}:{lineno}: marker `{name}` sits above `{declared}`")
        documented = set()
        for names, exempt, length in sections[fname]:
            lengths.append(length)
            for name in names:
                documented.add(name)
                if name not in seen and not exempt:
                    problems.append(f"map: `{fname}` documents chunk `{name}`, which has no marker")
        for name, lineno, _ in marks:
            if name not in documented:
                problems.append(f"{fname}:{lineno}: marker `{name}` has no bullet in the map")
    for name, bullets in sections.items():
        for names, _, length in bullets:
            if length > MAX_BULLET:
                problems.append(f"map: `{name}` bullet for {names} is {length} chars (cap {MAX_BULLET})")
    if lengths and sum(lengths) / len(lengths) > MAX_MEAN:
        problems.append(f"map: mean bullet length {sum(lengths) / len(lengths):.0f} (cap {MAX_MEAN})")
    for p in problems:
        print(p)
    if problems:
        print(f"map: {len(problems)} problem(s)")
        return 1
    print(f"map OK: {len(files)} files, {total} chunks, {len(lengths)} bullets, "
          f"mean {sum(lengths) / len(lengths):.0f} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
