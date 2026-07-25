"""Node 1 — turn a diff into structured schema changes. Fully deterministic.

Parsing is done with sqlglot against the projected output columns of the model
before and after the change, not with regex over the diff text: a column removed
from a CTE that never reached the output is not a schema change, and a column
renamed in the final SELECT is, even if the diff looks identical in size.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import sqlglot
from sqlglot import exp

from fuse.state import Change, FuseState

JINJA_CONFIG = re.compile(r"\{\{\s*config\(.*?\)\s*\}\}", re.DOTALL)
JINJA_STMT = re.compile(r"\{%.*?%\}", re.DOTALL)
JINJA_REF = re.compile(r"\{\{\s*ref\(\s*['\"]([\w.]+)['\"]\s*\)\s*\}\}")
JINJA_SOURCE = re.compile(
    r"\{\{\s*source\(\s*['\"]([\w]+)['\"]\s*,\s*['\"]([\w]+)['\"]\s*\)\s*\}\}"
)
JINJA_ANY = re.compile(r"\{\{.*?\}\}", re.DOTALL)


def strip_jinja(sql: str) -> str:
    """Make a dbt model parseable by sqlglot without changing its column shape."""
    sql = JINJA_CONFIG.sub("", sql)
    sql = JINJA_STMT.sub("", sql)
    sql = JINJA_REF.sub(lambda m: m.group(1).replace(".", "_"), sql)
    sql = JINJA_SOURCE.sub(lambda m: f"{m.group(1)}_{m.group(2)}", sql)
    sql = JINJA_ANY.sub("NULL", sql)
    return sql.strip()


def output_columns(sql: str, dialect: str = "snowflake") -> dict[str, str | None]:
    """Projected output column name -> declared type (from CAST), if any."""
    parsed = sqlglot.parse_one(strip_jinja(sql), read=dialect)
    select = parsed if isinstance(parsed, exp.Select) else parsed.find(exp.Select)
    if select is None:
        return {}
    columns: dict[str, str | None] = {}
    for projection in select.expressions:
        name = projection.alias_or_name
        if not name or name == "*":
            continue
        cast = projection.find(exp.Cast)
        columns[name] = cast.to.sql(dialect=dialect).upper() if cast else None
    return columns


def source_expression(sql: str, column: str, dialect: str = "snowflake") -> str | None:
    """The expression behind an output column, alias stripped — used to spot renames."""
    parsed = sqlglot.parse_one(strip_jinja(sql), read=dialect)
    select = parsed if isinstance(parsed, exp.Select) else parsed.find(exp.Select)
    if select is None:
        return None
    for projection in select.expressions:
        if projection.alias_or_name == column:
            inner = projection.this if isinstance(projection, exp.Alias) else projection
            return inner.sql(dialect=dialect)
    return None


def diff_model(
    before_sql: str, after_sql: str, *, file: str, model: str, dialect: str, snippet: str = ""
) -> list[Change]:
    before = output_columns(before_sql, dialect)
    after = output_columns(after_sql, dialect)

    dropped = [c for c in before if c not in after]
    added = [c for c in after if c not in before]
    changes: list[Change] = []

    # A single drop + single add whose underlying expression is identical is a rename,
    # which is recoverable with an alias, unlike a true drop.
    if len(dropped) == 1 and len(added) == 1:
        old_expr = source_expression(before_sql, dropped[0], dialect)
        new_expr = source_expression(after_sql, added[0], dialect)
        if old_expr and old_expr == new_expr:
            return [
                Change(
                    kind="rename_column",
                    file=file,
                    model=model,
                    column=dropped[0],
                    renamed_to=added[0],
                    snippet=snippet,
                )
            ]

    changes += [
        Change(kind="drop_column", file=file, model=model, column=c, from_type=before[c],
               snippet=snippet)
        for c in dropped
    ]
    changes += [
        Change(kind="add_column", file=file, model=model, column=c, to_type=after[c],
               snippet=snippet)
        for c in added
    ]
    changes += [
        Change(kind="retype_column", file=file, model=model, column=c, from_type=before[c],
               to_type=after[c], snippet=snippet)
        for c in before
        if c in after and before[c] != after[c] and (before[c] or after[c])
    ]
    return changes


# --------------------------------------------------------------------------- diffs


@dataclass
class Hunk:
    old_start: int
    old_len: int
    lines: list[str]


@dataclass
class FileDiff:
    path: str
    hunks: list[Hunk]
    deleted: bool = False


HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_unified_diff(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current: FileDiff | None = None
    hunk: Hunk | None = None

    for line in text.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            path = path.removeprefix("b/")
            current = FileDiff(path=path, hunks=[], deleted=path == "/dev/null")
            files.append(current)
            hunk = None
        elif line.startswith("@@") and current is not None:
            m = HUNK_HEADER.match(line)
            if m:
                hunk = Hunk(int(m.group(1)), int(m.group(2) or 1), [])
                current.hunks.append(hunk)
        elif hunk is not None and line[:1] in {" ", "+", "-"}:
            hunk.lines.append(line)
    return [f for f in files if f.hunks or f.deleted]


def apply_hunks(before: list[str], hunks: list[Hunk]) -> list[str]:
    """Apply parsed hunks in memory so a .patch can be analysed without touching the tree."""
    after: list[str] = []
    cursor = 0
    for hunk in hunks:
        start = hunk.old_start - 1
        after.extend(before[cursor:start])
        cursor = start
        for line in hunk.lines:
            tag, content = line[0], line[1:]
            if tag == " ":
                after.append(content)
                cursor += 1
            elif tag == "-":
                cursor += 1
            elif tag == "+":
                after.append(content)
    after.extend(before[cursor:])
    return after


def _git_show(repo: Path, rev: str, relpath: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "show", f"{rev}:{relpath}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _load_diff(state: FuseState) -> str:
    """`diff` is a patch file path, a git rev, or raw unified diff text."""
    raw = state.get("diff", "HEAD")
    repo = Path(state.get("repo_path", "."))

    path = Path(raw)
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8")
    if raw.lstrip().startswith(("diff --git", "--- ", "@@")):
        return raw
    args = ["git", "-C", str(repo), "diff", "--unified=3"]
    args += ["--staged"] if raw == "--staged" else [raw]
    return subprocess.run(args, capture_output=True, text=True, check=False).stdout


def parse_change(state: FuseState) -> dict:
    dialect = state.get("dialect", "snowflake")
    repo = Path(state.get("repo_path", "."))
    diff_text = _load_diff(state)
    changes: list[Change] = []
    trace = list(state.get("trace", []))

    for fd in parse_unified_diff(diff_text):
        if not fd.path.endswith(".sql"):
            continue
        model = Path(fd.path).stem
        target = repo / fd.path
        if not target.exists():
            # patch paths are usually relative to the data repo root
            target = repo / Path(fd.path).name
        if fd.deleted:
            changes.append(Change(kind="drop_model", file=fd.path, model=model))
            continue
        if not target.exists():
            trace.append(f"parse_change: skipped {fd.path} (not found under {repo})")
            continue

        before_lines = target.read_text(encoding="utf-8").splitlines()
        # If the patch is already applied in the tree, reconstruct the other side from git.
        applied = _git_show(repo, "HEAD", fd.path)
        if applied is not None and applied.splitlines() != before_lines:
            before_lines, after_lines = applied.splitlines(), before_lines
        else:
            after_lines = apply_hunks(before_lines, fd.hunks)

        snippet = "\n".join(line for h in fd.hunks for line in h.lines if line[:1] in "+-")
        changes.extend(
            diff_model(
                "\n".join(before_lines),
                "\n".join(after_lines),
                file=fd.path,
                model=model,
                dialect=dialect,
                snippet=snippet,
            )
        )

    trace.append(f"parse_change: {len(changes)} change(s)")
    return {"changes": changes, "trace": trace}
