#!/usr/bin/env python3
"""MRK-114: static check of the Alembic migrations between two heads in a verified release (no import, no DB).

Usage: check-migration.py VERSIONS_DIR OLD_HEAD NEW_HEAD
The chain NEW_HEAD -> ... -> OLD_HEAD must be linear and every migration file must pass an AST WHITELIST (fail closed:
anything not explicitly allowed is refused - Codex review P1, the earlier regex check could be bypassed by helpers,
aliases or arbitrary Python):

module level  docstring; `from alembic import op`; `import sqlalchemy as sa`; `from sqlalchemy.dialects import ...`;
              `from typing import ...` / `from __future__ import ...`; constant assignments of revision,
              down_revision, branch_labels, depends_on (annotations only plain type names / None); `def upgrade()`
              and `def downgrade()` without parameters, defaults or decorators, return annotation only None
              (downgrade's body is never run automatically and is not checked). Nothing else runs at import time.
upgrade()     docstring / pass; `op.create_table(...)`, `op.create_index(...)`, `op.add_column(...)`;
              `with op.batch_alter_table(...) as <name>:` whose body is only `<name>.add_column(...)`.
arguments     constants, lists/tuples/dicts, keywords, `sa.<...>(...)` constructors, `op.f("...")` - no other names,
              no lambdas, comprehensions, attribute access on anything but `sa`, no `sa.text`/`literal_column`/`func`.
add_column    the sa.Column must say nullable=True or carry a server_default.

Necessary, not sufficient: the rehearsal still runs the old and the new application against a migrated copy of the
database (deploy-migration-v3.sh).
"""
import ast
import sys
from pathlib import Path

ALLOWED_OPS = {"create_table", "create_index", "add_column"}
META = {"revision", "down_revision", "branch_labels", "depends_on"}
SA_FORBIDDEN = {"text", "literal_column", "func", "event", "DDL", "exc", "engine", "create_engine", "orm", "inspect"}


class NotAdditive(Exception):
    pass


def where(node, name):
    return f"{name}:{getattr(node, 'lineno', '?')}"


def check_expr(node, name):
    """Arguments may only build schema objects."""
    if isinstance(node, ast.Constant):
        return
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for e in node.elts:
            check_expr(e, name)
        return
    if isinstance(node, ast.Dict):
        for e in [*node.keys, *node.values]:
            if e is not None:
                check_expr(e, name)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant):
        return
    if isinstance(node, ast.Attribute) and sa_path(node):
        return
    if isinstance(node, ast.Call):
        if sa_path(node.func) or is_op_f(node):
            for a in node.args:
                check_expr(a, name)
            for k in node.keywords:
                if k.arg is None:
                    raise NotAdditive(f"{where(node, name)}: **kwargs")
                check_expr(k.value, name)
            return
    raise NotAdditive(f"{where(node, name)}: {ast.dump(node)[:80]}")


def sa_path(node):
    """sa.X or sa.X.Y (e.g. sa.Integer, postgresql.JSONB via `from sqlalchemy.dialects import postgresql`)."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not (isinstance(node, ast.Name) and node.id in ("sa", "postgresql", "sqlite") and parts):
        return False
    if any(p in SA_FORBIDDEN or p.startswith("_") for p in parts):
        raise NotAdditive(f"sa.{'.'.join(reversed(parts))} is not allowed")
    return True


def is_op_f(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "f"
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "op"
            and len(node.args) == 1 and isinstance(node.args[0], ast.Constant) and not node.keywords)


SAFE_TYPE_NAMES = {"str", "None", "Union", "Optional", "Sequence", "Tuple", "tuple", "list", "List"}


def check_annotation(node, name):
    """Annotations are evaluated at import time (Codex review P1): only plain type names, None and their
    subscripts / unions, e.g. `str`, `Union[str, Sequence[str], None]`, `str | None`, `-> None`."""
    if node is None:
        return
    if isinstance(node, ast.Constant) and (node.value is None or isinstance(node.value, str) and node.value.isidentifier()):
        return
    if isinstance(node, ast.Name) and node.id in SAFE_TYPE_NAMES:
        return
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in SAFE_TYPE_NAMES:
        check_annotation(node.slice, name)
        return
    if isinstance(node, ast.Tuple):
        for e in node.elts:
            check_annotation(e, name)
        return
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        check_annotation(node.left, name)
        check_annotation(node.right, name)
        return
    raise NotAdditive(f"{where(node, name)}: annotation {ast.dump(node)[:60]}")


def check_signature(fn, name):
    """upgrade()/downgrade(): no parameters, defaults or decorators; return annotation only None (all of these are
    evaluated when Alembic imports the revision)."""
    a = fn.args
    if (a.posonlyargs or a.args or a.vararg or a.kwonlyargs or a.kwarg or a.defaults or a.kw_defaults
            or fn.decorator_list or getattr(fn, "type_params", None)):
        raise NotAdditive(f"{where(fn, name)}: {fn.name}() must take no parameters and have no decorators")
    if fn.returns is not None and not (isinstance(fn.returns, ast.Constant) and fn.returns.value is None):
        raise NotAdditive(f"{where(fn, name)}: {fn.name}() return annotation must be None")


def check_call(call, receiver, name, ops):
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name) and call.func.value.id == receiver):
        raise NotAdditive(f"{where(call, name)}: only {receiver}.<operation>(...) calls")
    op = call.func.attr
    allowed = ALLOWED_OPS if receiver == "op" else {"add_column"}
    if op not in allowed:
        raise NotAdditive(f"{where(call, name)}: {receiver}.{op}")
    for a in call.args:
        check_expr(a, name)
    for k in call.keywords:
        if k.arg is None:
            raise NotAdditive(f"{where(call, name)}: **kwargs")
        check_expr(k.value, name)
    if op == "add_column":
        columns = [a for a in call.args if isinstance(a, ast.Call) and sa_path(a.func) and a.func.attr == "Column"]
        if len(columns) != 1:
            raise NotAdditive(f"{where(call, name)}: add_column needs one sa.Column(...)")
        kw = {k.arg: k.value for k in columns[0].keywords}
        nullable = isinstance(kw.get("nullable"), ast.Constant) and kw["nullable"].value is True
        if not (nullable or "server_default" in kw):
            raise NotAdditive(f"{where(call, name)}: add_column without nullable=True or server_default")
    ops.append(op)


def check_upgrade(fn, name):
    ops = []
    check_signature(fn, name)
    for stmt in fn.body:
        if isinstance(stmt, ast.Pass) or (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)):
            continue
        if isinstance(stmt, ast.Expr):
            check_call(stmt.value, "op", name, ops)
            continue
        if isinstance(stmt, ast.With) and len(stmt.items) == 1:
            item = stmt.items[0]
            ctx = item.context_expr
            if (isinstance(ctx, ast.Call) and isinstance(ctx.func, ast.Attribute) and ctx.func.attr == "batch_alter_table"
                    and isinstance(ctx.func.value, ast.Name) and ctx.func.value.id == "op"
                    and isinstance(item.optional_vars, ast.Name)):
                for a in ctx.args:
                    check_expr(a, name)
                for k in ctx.keywords:
                    if k.arg is None:
                        raise NotAdditive(f"{where(ctx, name)}: **kwargs")
                    check_expr(k.value, name)
                alias = item.optional_vars.id
                if alias in ("op", "sa"):
                    raise NotAdditive(f"{where(stmt, name)}: alias shadows {alias}")
                for inner in stmt.body:
                    if not isinstance(inner, ast.Expr):
                        raise NotAdditive(f"{where(inner, name)}: only {alias}.add_column(...) inside batch_alter_table")
                    check_call(inner.value, alias, name, ops)
                ops.append("batch_alter_table")
                continue
        raise NotAdditive(f"{where(stmt, name)}: {type(stmt).__name__} is not allowed in upgrade()")
    return ops


def check_module(tree, name):
    upgrade, seen = None, set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue
        if isinstance(stmt, ast.ImportFrom) and stmt.module in ("alembic",) and [a.name for a in stmt.names] == ["op"] \
                and stmt.names[0].asname is None:
            continue
        if isinstance(stmt, ast.Import) and [(a.name, a.asname) for a in stmt.names] == [("sqlalchemy", "sa")]:
            continue
        if isinstance(stmt, ast.ImportFrom) and stmt.module in ("typing", "__future__", "sqlalchemy.dialects"):
            continue
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            if all(isinstance(t, ast.Name) and t.id in META for t in targets) and stmt.value is not None:
                if isinstance(stmt, ast.AnnAssign):
                    check_annotation(stmt.annotation, name)
                check_expr(stmt.value, name)
                continue
        # exactly one definition each: a first definition's defaults/decorators run at import even when a second,
        # harmless one replaces it (Codex review P1) - every definition is checked and duplicates are refused
        if isinstance(stmt, ast.FunctionDef) and stmt.name in ("upgrade", "downgrade"):
            check_signature(stmt, name)
            if stmt.name in seen:
                raise NotAdditive(f"{where(stmt, name)}: second definition of {stmt.name}()")
            seen.add(stmt.name)
            if stmt.name == "upgrade":
                upgrade = stmt
            continue
        raise NotAdditive(f"{where(stmt, name)}: {type(stmt).__name__} at module level")
    if upgrade is None:
        raise NotAdditive(f"{name}: no upgrade()")
    return check_upgrade(upgrade, name)


def meta(tree):
    values = {}
    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id in ("revision", "down_revision") and stmt.value is not None:
                    try:
                        values[t.id] = ast.literal_eval(stmt.value)
                    except ValueError:
                        values[t.id] = None
    return values.get("revision"), values.get("down_revision")


def main():
    if len(sys.argv) != 4:
        print("Usage: check-migration.py VERSIONS_DIR OLD_HEAD NEW_HEAD", file=sys.stderr)
        return 2
    versions, old_head, new_head = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    by_rev = {}
    try:
        for path in sorted(versions.glob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
            except SyntaxError as e:
                raise NotAdditive(f"{path.name}: syntax error {e.lineno}")
            rev, down = meta(tree)
            if isinstance(rev, str):
                by_rev[rev] = (path.name, tree, down)
        chain, cur = [], new_head
        while cur != old_head:
            if cur not in by_rev:
                raise NotAdditive(f"revision {cur} not found between {new_head} and {old_head}")
            name, tree, down = by_rev[cur]
            if not isinstance(down, str):
                raise NotAdditive(f"{name}: merge or root migration")
            chain.append((cur, name, tree))
            cur = down
            if len(chain) > 50:
                raise NotAdditive("chain longer than 50 revisions")
        if not chain:
            raise NotAdditive("old and new head are the same")
        for rev, name, tree in reversed(chain):
            ops = check_module(tree, name)
            print(f"MIGRATION_OPS: {rev} ({name}): {', '.join(ops) or 'none'}")
    except NotAdditive as e:
        print(f"MIGRATION_OPS_NOT_ADDITIVE: {e}")
        return 1
    print(f"MIGRATION_OPS_ADDITIVE: {old_head} -> {new_head} ({len(chain)} revision(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
