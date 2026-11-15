#!/usr/bin/env python3
"""MRK-114: static check of the Alembic migrations between two heads in a verified release (no import, no DB).

Usage: check-migration.py VERSIONS_DIR OLD_HEAD NEW_HEAD
The chain NEW_HEAD -> ... -> OLD_HEAD must be linear and every upgrade() may only ADD schema: op.create_table,
op.create_index, op.add_column / batch_op.add_column with nullable=True or a server_default, op.batch_alter_table.
Anything else (drop, alter_column, rename, execute, bulk data changes, NOT NULL column without default, merge
migrations) -> MIGRATION_OPS_NOT_ADDITIVE and exit 1. This is necessary, not sufficient: the rehearsal still runs the
old and the new application against a migrated copy of the database (deploy-migration-v3.sh).
"""
import re
import sys
from pathlib import Path

ALLOWED = {"create_table", "create_index", "add_column", "batch_alter_table", "f"}  # op.f = naming helper only
_REV = re.compile(r"^revision\s*(?::\s*\w+\s*)?=\s*['\"]([^'\"]+)['\"]", re.M)
_DOWN = re.compile(r"^down_revision\s*(?::[^=]+)?=\s*(.+)$", re.M)
_CALL = re.compile(r"\b(op|batch\w*)\.(\w+)\(")


def fail(message):
    print(f"MIGRATION_OPS_NOT_ADDITIVE: {message}")
    sys.exit(1)


def call_args(text, start):
    """Text of the balanced (...) that starts at text[start] == '('."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
    fail("unbalanced call")


def upgrade_body(text, name):
    m = re.search(r"^def upgrade\(\)[^:]*:\n(.*?)(?=^def |\Z)", text, re.M | re.S)
    if not m:
        fail(f"{name}: no upgrade()")
    return m.group(1)


def main():
    if len(sys.argv) != 4:
        print("Usage: check-migration.py VERSIONS_DIR OLD_HEAD NEW_HEAD", file=sys.stderr)
        return 2
    versions, old_head, new_head = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    by_rev = {}
    for path in sorted(versions.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        rev = _REV.search(text)
        if not rev:
            continue
        down = _DOWN.search(text)
        downs = re.findall(r"['\"]([^'\"]+)['\"]", down.group(1)) if down else []
        by_rev[rev.group(1)] = (path.name, text, downs)
    chain, cur = [], new_head
    while cur != old_head:
        if cur not in by_rev:
            fail(f"revision {cur} not found between {new_head} and {old_head}")
        name, text, downs = by_rev[cur]
        if len(downs) != 1:
            fail(f"{name}: merge or root migration ({len(downs)} down revisions)")
        chain.append((cur, name, text))
        cur = downs[0]
        if len(chain) > 50:
            fail("chain longer than 50 revisions")
    if not chain:
        fail("old and new head are the same")
    for rev, name, text in reversed(chain):
        body = upgrade_body(text, name)
        ops = []
        for m in _CALL.finditer(body):
            op = m.group(2)
            if op not in ALLOWED:
                fail(f"{name}: {m.group(1)}.{op}")
            if op == "add_column":
                args = call_args(body, m.end() - 1)
                if not re.search(r"nullable\s*=\s*True|server_default\s*=", args):
                    fail(f"{name}: add_column without nullable=True or server_default")
            ops.append(op)
        if re.search(r"get_bind\(|\.query\(|\bSession\(|\bconnection\.|bulk_insert|\btext\(", body):
            fail(f"{name}: data access in upgrade()")
        print(f"MIGRATION_OPS: {rev} ({name}): {', '.join(ops) or 'none'}")
    print(f"MIGRATION_OPS_ADDITIVE: {old_head} -> {new_head} ({len(chain)} revision(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
