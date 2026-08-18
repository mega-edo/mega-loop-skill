"""Grading the instrumentation in a repository, before it has emitted a single trace.

The trace grader (`checks.py`) answers *did the traces come out usable*. It cannot run until the
app has run, against a live platform, with credentials. This answers a narrower question earlier:
*given this source, which of the known problems is already decided?*

Some are. An auto-instrumentor for a database driver is a call in the code; whether it fires is
not in doubt, and the traces it will bury are not either. Whether a span carries a kind is decided
where the span is opened. Both are visible in an import and a call site.

Most are not, and the split matters more than the checks do:

* whether trace context survives a real hop is a property of the deployment, not the source;
* whether a platform assigns a default kind to a bare span is the platform's behaviour;
* what share of a trace is mechanical needs traces to count.

So this is deliberately **not** a substitute for grading real traces, and says so in its own
output. It is the half of the answer available while the developer is still typing.

Every finding must name a `file:line` a reader can open. A rule that cannot do that — "this file
feels under-instrumented" — is guesswork with a line number attached, and guesswork here is worse
than silence: a developer who is told to fix something that is not broken stops reading the tool.
When a rule cannot prove its case from the source, it stays quiet and lets the trace grader
answer.
"""

from __future__ import annotations

import ast
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from trace_validator import contract as C
from trace_validator.checks import Check

#: Auto-instrumentors that emit one span per round-trip of something that is not agent work.
#: Naming them individually rather than pattern-matching `*Instrumentor`: the LLM ones
#: (OpenAI, Anthropic, LangChain…) are exactly what this skill asks developers to install, and a
#: rule that cannot tell those apart would fire on correct instrumentation.
NOISY_INSTRUMENTORS = frozenset(
    {
        "SQLAlchemyInstrumentor",
        "Psycopg2Instrumentor",
        "PsycopgInstrumentor",
        "AsyncPGInstrumentor",
        "MySQLInstrumentor",
        "PymongoInstrumentor",
        "RedisInstrumentor",
        "ElasticsearchInstrumentor",
        "RequestsInstrumentor",
        "HTTPXClientInstrumentor",
        "AioHttpClientInstrumentor",
        "URLLib3Instrumentor",
        "BotocoreInstrumentor",
        "CeleryInstrumentor",
        "KafkaInstrumentor",
        "PikaInstrumentor",
    }
)

#: Calls that open a span. `start_as_current_span` is also used as a decorator; both forms parse
#: to a Call node, so one set covers them.
SPAN_OPENERS = frozenset({"start_as_current_span", "start_span"})

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        "build",
        "dist",
        ".tox",
        "site-packages",
        # A test opens spans to assert on them, so it is *supposed* to hand-roll one without a
        # kind. Graded, a healthy suite reads as dozens of findings a developer has to walk
        # before learning none of them ship — which teaches them to skim the whole board.
        "tests",
        "test",
    }
)


#: Source extensions worth counting when deciding what a repository is written in. Enough to
#: name the language in a message; not a package manifest, which a polyglot repo has several of.
_LANGUAGES: dict[str, str] = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".cs": "C#",
    ".php": "PHP",
    ".rs": "Rust",
    ".ex": "Elixir",
    ".scala": "Scala",
    ".swift": "Swift",
}


class SourceGrade(BaseModel):
    model_config = ConfigDict(frozen=True)

    scanned: int = 0  # files this grader could read
    checks: tuple[Check, ...] = ()
    #: Language → file count for everything present, readable or not. A repository this grader
    #: cannot parse must not be reported as clean: "no findings" and "nothing was read" look
    #: identical on a board and mean opposite things.
    languages: dict[str, int] = {}

    @property
    def findings(self) -> list[Check]:
        return [c for c in self.checks if c.failing]

    @property
    def unreadable(self) -> dict[str, int]:
        """Languages present in bulk that this grader has no parser for."""
        return {
            name: count
            for name, count in self.languages.items()
            if name != "Python" and count >= _UNREADABLE_MIN
        }

    @property
    def ok(self) -> bool:
        return not self.findings


#: Below this a language is incidental — a build script, one helper — and saying "I cannot read
#: your Go" about two files would be noise.
_UNREADABLE_MIN = 5


def _is_test(path: Path) -> bool:
    """A test module, wherever it sits — `tests/` catches most, this catches the strays."""
    return path.name.startswith("test_") or path.name.endswith("_test.py")


def python_files(root: Path) -> list[Path]:
    """Every `.py` under ROOT that could run in production.

    Vendored code and tests are skipped rather than reported. A finding in `site-packages` names
    a file the developer cannot edit; a finding in a test names a span written to be asserted on.
    Both are unactionable, and a board full of them is one a developer learns to skim.
    """
    out: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts) or _is_test(path):
            continue
        out.append(path)
    return out


def _where(root: Path, path: Path, node: ast.AST) -> str:
    try:
        rel: Path | str = path.relative_to(root)
    except ValueError:  # a file outside the scanned root — print what we were given
        rel = path
    return f"{rel}:{getattr(node, 'lineno', 0)}"


def _called_name(node: ast.Call) -> str:
    """The rightmost name of whatever is being called — `a.b.C()` -> `C`, `C()` -> `C`."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _instrument_call_target(node: ast.Call) -> str:
    """For `XInstrumentor().instrument()`, the `X` — otherwise "".

    Matching the `.instrument()` call rather than the constructor on purpose: constructing an
    instrumentor and never instrumenting emits nothing, and a rule that fired on the import alone
    would flag a conditional block that never runs.
    """
    if _called_name(node) != "instrument":
        return ""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return ""
    inner = func.value
    if isinstance(inner, ast.Call):  # XInstrumentor().instrument()
        return _called_name(inner)
    if isinstance(inner, ast.Name):  # instrumentor = XInstrumentor(); instrumentor.instrument()
        return inner.id
    return ""


def _mentions_kind(node: ast.AST) -> bool:
    """Does this subtree name the span-kind key literally anywhere?

    Only the literal counts — a kind reached through a variable is invisible to a reader of the
    tree, which is what the enclosing-scope exemption below is for.
    """
    return any(isinstance(sub, ast.Constant) and sub.value == C.OI_KIND for sub in ast.walk(node))


def _kindless_span_sites(tree: ast.AST, root: Path, path: Path) -> list[str]:
    """Span-opening calls whose enclosing function never names a span kind.

    Scoped to the **function**, not the file. A tracing module usually has one place that sets a
    kind — the model seam — and several helpers that open spans without one; exempting the whole
    file because of that seam hides exactly the helpers worth reporting. Scoped to the function,
    the seam exempts itself and the helpers do not.

    Any enclosing function counts, not just the innermost. A decorator that sets the kind in its
    outer scope and opens the span in a nested wrapper is one function to a reader, and reporting
    the wrapper would be reporting the closure.
    """
    hits: list[str] = []

    def walk(node: ast.AST, guarded: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                walk(child, guarded or _mentions_kind(child))
                continue
            if (
                isinstance(child, ast.Call)
                and _called_name(child) in SPAN_OPENERS
                and not guarded
                and not _mentions_kind(child)
            ):
                hits.append(_where(root, path, child))
            walk(child, guarded)

    # A module-level mention (a shared constant the whole file reads through) guards everything:
    # the rule cannot follow the name to its use, and reporting every site in such a file would
    # report the indirection rather than a missing kind.
    module_level = any(
        _mentions_kind(n)
        for n in ast.iter_child_nodes(tree)
        if not isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    )
    walk(tree, module_level)
    return hits


def census(root: Path) -> dict[str, int]:
    """Language → file count for what is actually in ROOT, readable or not."""
    counts: dict[str, int] = {}
    for path in root.rglob("*"):
        language = _LANGUAGES.get(path.suffix)
        if language is None or not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        counts[language] = counts.get(language, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def _traces_at_all(tree: ast.AST) -> bool:
    """Does this module show any sign of tracing — a span, an instrumentor, an OTel import?

    Deliberately generous. The question it answers is "has anyone instrumented this repository",
    and a file that only imports `opentelemetry` still answers yes; a repository where nothing
    does is one where tracing has not been started, which is a different situation from a
    repository whose tracing is wrong.
    """
    roots = ("opentelemetry", "openinference")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _called_name(node) in {*SPAN_OPENERS, "instrument"}:
            return True
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] in roots for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in roots:
            return True
    return False


def _uninstrumented_check(instrumented: bool, scanned: int) -> Check:
    """Always on the board, like every other check — a rule that only appears when it fails is
    one a reader cannot confirm ran.

    ``instrumented`` is passed true when any file could not be parsed: claiming a repository
    traces nothing means having read all of it, and a file this Python choked on may be exactly
    the one that sets up the tracer.
    """
    return Check(
        id="L0_any_instrumentation",
        tier="hard",
        verdict="pass" if instrumented else "fail",
        detail=(
            "No tracing at all. Nothing in this repository opens a span, enables an "
            "instrumentor, or imports OpenTelemetry, so there is nothing here to grade"
        ),
        fix=(
            "This board is empty because the code emits nothing, not because it is correct — "
            "the other checks passed over an empty set. Start the instrumentation first: "
            "/mega-loop:trace-gen decides what one request is, installs the kit, and grades the "
            "traces that come out."
        ),
        sample_size=scanned,
        fail_count=0 if instrumented else scanned,
        evidence=(),
    )


def scan(root: Path) -> SourceGrade:
    """Grade the instrumentation visible in ROOT's Python sources."""
    files = python_files(root)
    noisy: list[str] = []
    kindless: list[str] = []
    instrumented = False
    unread = False  # a file this Python could not parse might be the one that traces

    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        except (SyntaxError, ValueError, OSError):
            unread = True
            continue  # a file this Python cannot parse is not evidence of anything

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and (target := _instrument_call_target(node)) in NOISY_INSTRUMENTORS
            ):
                noisy.append(f"{_where(root, path, node)} ({target})")
        kindless += _kindless_span_sites(tree, root, path)
        instrumented = instrumented or _traces_at_all(tree)

    return SourceGrade(
        scanned=len(files),
        languages=census(root),
        checks=(
            # First, because when it fails every other check passed over an empty set and a
            # clean board would say the opposite of the truth.
            _uninstrumented_check(instrumented or unread, len(files)),
            _noisy_check(noisy, len(files)),
            _kindless_check(kindless, len(files)),
        ),
    )


def _noisy_check(hits: list[str], scanned: int) -> Check:
    return Check(
        id="L1_mechanical_autoinstrumentation",
        tier="soft",
        verdict="warn" if hits else "pass",
        detail=(
            "An auto-instrumentor for a driver is enabled. It emits one span per round-trip, none "
            "of which can seat a replay or feed a detector, and they arrive in the thousands"
        ),
        fix=(
            "Put the call behind an environment flag defaulting to OFF. Query-level spans are a "
            "real debugging tool for an hour of investigation, not the default shape of every "
            "trace the service produces."
        ),
        sample_size=scanned,
        fail_count=len(hits),
        evidence=tuple(hits),
    )


def _kindless_check(hits: list[str], scanned: int) -> Check:
    return Check(
        id="L2_span_kind_at_open",
        tier="soft",
        verdict="warn" if hits else "pass",
        detail=(
            "A span is opened without an `openinference.span.kind`, by a function that never sets "
            "one. Detectors read LLM, AGENT, TOOL and RETRIEVER and walk past everything else, so "
            "the step is invisible to them — silently"
        ),
        fix=(
            f"Pass `{C.OI_KIND}` when opening the span — TOOL for a step the agent calls, "
            "RETRIEVER for a lookup, LLM for a model call, AGENT for a unit of agent work. If a "
            "shared helper opens these spans, give the helper a kind parameter and set it there."
        ),
        sample_size=scanned,
        fail_count=len(hits),
        evidence=tuple(hits),
    )
