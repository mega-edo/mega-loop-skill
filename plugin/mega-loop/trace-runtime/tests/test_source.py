"""The source grader, and — mostly — the cases it must stay quiet on.

A source rule earns its place by discriminating, not by firing. The repository already contains
the proof material for that: `examples/orders-agent` holds the same agent instrumented three ways,
one of them deliberately wrong. A rule that cannot tell those two files apart is measuring nothing,
so that pair is asserted here rather than described.
"""

from __future__ import annotations

from pathlib import Path

from trace_validator.cli import main
from trace_validator.source import scan

_REPO = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, name: str, body: str) -> Path:
    (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


def _check(grade, cid: str):
    return next(c for c in grade.checks if c.id == cid)


def test_a_database_instrumentor_is_reported(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        "app.py",
        "from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor\n"
        "SQLAlchemyInstrumentor().instrument(engine=engine)\n",
    )
    check = _check(scan(root), "L1_mechanical_autoinstrumentation")
    assert check.verdict == "warn"
    assert check.evidence == ("app.py:2 (SQLAlchemyInstrumentor)",)


def test_an_llm_instrumentor_is_not(tmp_path: Path) -> None:
    """The kit tells developers to install exactly these. Firing on them would make the skill
    contradict its own instructions — the one failure mode that costs a developer's trust."""
    root = _write(
        tmp_path,
        "app.py",
        "from openinference.instrumentation.openai import OpenAIInstrumentor\n"
        "OpenAIInstrumentor().instrument()\n",
    )
    assert _check(scan(root), "L1_mechanical_autoinstrumentation").verdict == "pass"


def test_constructing_an_instrumentor_without_instrumenting_is_not_reported(tmp_path: Path) -> None:
    """It emits nothing until `.instrument()` is called, so neither does the check."""
    root = _write(tmp_path, "app.py", "probe = SQLAlchemyInstrumentor()\n")
    assert _check(scan(root), "L1_mechanical_autoinstrumentation").verdict == "pass"


def test_a_span_opened_without_a_kind_is_reported(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        "agent.py",
        "def step():\n"
        "    with tracer.start_as_current_span('search') as sp:\n"
        "        sp.set_attribute('input.value', q)\n",
    )
    check = _check(scan(root), "L2_span_kind_at_open")
    assert check.verdict == "warn"
    assert check.evidence == ("agent.py:2",)


def test_the_function_that_sets_a_kind_exempts_only_itself(tmp_path: Path) -> None:
    """The rule that made this worth building.

    A tracing module has one seam that sets a kind and several helpers that do not. Exempting the
    whole file because of the seam hides the helpers — which is where the missing kinds actually
    are. Both functions live here; exactly one must be reported.
    """
    root = _write(
        tmp_path,
        "obs.py",
        "def model_seam(name):\n"
        "    with tracer.start_as_current_span(\n"
        "        name, attributes={'openinference.span.kind': 'LLM'}\n"
        "    ) as sp:\n"
        "        return sp\n"
        "\n"
        "def traced(name):\n"
        "    with tracer.start_as_current_span(name) as sp:\n"
        "        return sp\n",
    )
    check = _check(scan(root), "L2_span_kind_at_open")
    assert check.evidence == ("obs.py:8",), "only the helper without a kind"


def test_a_nested_wrapper_inherits_its_decorator_scope(tmp_path: Path) -> None:
    """A decorator that names the kind outside and opens the span in a closure is one function to
    a reader. Reporting the wrapper would be reporting the closure, not a defect."""
    root = _write(
        tmp_path,
        "deco.py",
        "def traced(kind):\n"
        "    attrs = {'openinference.span.kind': kind}\n"
        "    def decorator(fn):\n"
        "        def wrapper(*a):\n"
        "            with tracer.start_as_current_span(fn.__name__, attributes=attrs):\n"
        "                return fn(*a)\n"
        "        return wrapper\n"
        "    return decorator\n",
    )
    assert _check(scan(root), "L2_span_kind_at_open").verdict == "pass"


def test_vendored_code_is_not_scanned(tmp_path: Path) -> None:
    """A finding in a directory the developer cannot edit is an unactionable failure."""
    vendored = tmp_path / ".venv" / "lib"
    vendored.mkdir(parents=True)
    (vendored / "thing.py").write_text("SQLAlchemyInstrumentor().instrument()\n", encoding="utf-8")
    grade = scan(tmp_path)
    assert grade.scanned == 0
    assert _check(grade, "L1_mechanical_autoinstrumentation").verdict == "pass"


def test_an_unparseable_file_is_not_evidence(tmp_path: Path) -> None:
    root = _write(tmp_path, "broken.py", "def (:\n")
    assert scan(root).ok


def test_it_tells_the_examples_apart() -> None:
    """The discrimination proof, on the repository's own worked example.

    `orders_agent_naive.py` is the file written to be plausible and wrong;
    `orders_agent_instrumented.py` uses the kit. A rule that flags both, or neither, is not
    measuring instrumentation.
    """
    examples = _REPO / "examples" / "orders-agent"
    sites = _check(scan(examples), "L2_span_kind_at_open").evidence
    assert sites, "the naive example must be caught"
    assert all(s.startswith("orders_agent_naive.py:") for s in sites), sites


def test_the_kit_itself_is_clean() -> None:
    """The code this skill hands developers has to pass the skill's own source rules."""
    assert scan(_REPO / "kits" / "python").ok


def test_exit_codes(tmp_path: Path) -> None:
    """Same three-way contract as the trace grader: 0 clean, 1 findings, 2 could not look."""
    clean = tmp_path / "clean"
    clean.mkdir()
    # Instrumented, with nothing wrong with it. A file that merely parses is NOT the clean case:
    # a repository that traces nothing exits 1 now, because it is not ready and saying so is the
    # whole point of L0.
    (clean / "a.py").write_text(
        "from opentelemetry import trace\n\n"
        "with trace.get_tracer('t').start_as_current_span(\n"
        "    'x', attributes={'openinference.span.kind': 'CHAIN'}\n"
        "):\n    pass\n",
        encoding="utf-8",
    )
    assert main(["--source", str(clean)]) == 0

    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert main(["--source", str(bare)]) == 1  # no tracing at all is a finding

    dirty = tmp_path / "dirty"
    dirty.mkdir()
    (dirty / "a.py").write_text("RedisInstrumentor().instrument()\n", encoding="utf-8")
    assert main(["--source", str(dirty)]) == 1

    assert main(["--source", str(tmp_path / "nope")]) == 2


def test_the_report_says_what_source_cannot_answer(tmp_path: Path, capsys) -> None:
    """A clean board here is not a pass, and the output must not let a reader think it is."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    main(["--source", str(tmp_path)])
    out = capsys.readouterr().out
    assert "need real traces" in out


def test_a_test_module_is_not_graded(tmp_path: Path) -> None:
    """A test opens spans to assert on them, so it hand-rolls kindless ones by design. Graded,
    mega-loop's own suite produced 22 findings, every one of them unactionable — and a board a
    developer has to triage before learning none of it ships is a board they stop reading.

    Both shapes: a `tests/` package, and a stray `test_*.py` beside the code it covers.
    """
    opener = "tracer.start_as_current_span('x')\n"
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_thing.py").write_text(opener, encoding="utf-8")
    (tmp_path / "test_stray.py").write_text(opener, encoding="utf-8")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")

    grade = scan(tmp_path)
    assert grade.scanned == 1  # app.py alone
    assert _check(grade, "L2_span_kind_at_open").fail_count == 0


def test_json_carries_every_site_while_the_terminal_folds_the_tail(tmp_path: Path, capsys) -> None:
    """Truncation is a display choice. Reporting 22 sites and handing a caller 5 makes the
    machine-readable output the one that cannot be acted on, which is backwards."""
    body = "".join(f"tracer.start_as_current_span('s{i}')\n" for i in range(9))
    (tmp_path / "app.py").write_text(body, encoding="utf-8")

    grade = scan(tmp_path)
    assert len(_check(grade, "L2_span_kind_at_open").evidence) == 9

    main(["--source", str(tmp_path), "--json"])
    assert '"app.py:9"' in capsys.readouterr().out  # the ninth site, past the printed five

    main(["--source", str(tmp_path)])
    assert "… and 4 more" in capsys.readouterr().out


def test_a_repository_it_cannot_read_is_not_reported_as_clean(tmp_path: Path, capsys) -> None:
    """The dangerous silence. A Go repository has no `.py` files, so every check passes
    vacuously and the board reads as a pass — to a developer whose agent is entirely unmeasured.
    """
    for i in range(8):
        (tmp_path / f"svc{i}.go").write_text("package main\n", encoding="utf-8")

    main(["--source", str(tmp_path)])
    out = capsys.readouterr().out

    assert "Go (8)" in out
    assert "parses Python" in out
    assert "Nothing the source can decide is wrong" not in out


def test_a_clean_python_board_still_names_what_it_did_not_read(tmp_path: Path, capsys) -> None:
    """The polyglot case, which is worse than the pure one: there IS a board, it IS clean, and
    the part of the repository that actually serves traffic was never opened."""
    (tmp_path / "helper.py").write_text("from opentelemetry import trace\n", encoding="utf-8")
    for i in range(30):
        (tmp_path / f"handler{i}.go").write_text("package main\n", encoding="utf-8")

    grade = scan(tmp_path)
    assert grade.ok  # the Python it could read is fine…
    assert grade.unreadable == {"Go": 30}  # …and that is not the whole repository

    main(["--source", str(tmp_path)])
    out = capsys.readouterr().out
    assert "Not read: Go (30)" in out


def test_a_stray_file_in_another_language_is_not_worth_a_warning(tmp_path: Path) -> None:
    """A build script or one helper is incidental. Warning about it teaches the reader to skim
    the line that matters."""
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tool.go").write_text("package main\n", encoding="utf-8")

    assert scan(tmp_path).unreadable == {}


def test_a_repository_with_no_tracing_is_not_reported_as_correct(tmp_path: Path, capsys) -> None:
    """The greenfield trap, found by running the skill on a stripped repository: every check
    passes over an empty set, so the board reads as a pass on code that emits nothing at all."""
    (tmp_path / "app.py").write_text("def ask(q):\n    return q.upper()\n", encoding="utf-8")

    grade = scan(tmp_path)
    assert not grade.ok
    assert _check(grade, "L0_any_instrumentation").verdict == "fail"

    main(["--source", str(tmp_path)])
    out = capsys.readouterr().out
    assert "No tracing at all" in out
    assert "trace-gen" in out  # and it says which verb starts one


def test_any_sign_of_tracing_clears_it(tmp_path: Path) -> None:
    """Generous on purpose: the question is whether anyone has started, not whether they
    finished. An import alone answers it, and a repo that only auto-instruments has no spans of
    its own to find."""
    for body in (
        "from opentelemetry import trace\n",
        "import opentelemetry.sdk\n",
        "from openinference.instrumentation.openai import OpenAIInstrumentor\n",
        "OpenAIInstrumentor().instrument()\n",
        "tracer.start_as_current_span('x')\n",
    ):
        root = tmp_path / f"case{abs(hash(body))}"
        root.mkdir()
        (root / "app.py").write_text(body, encoding="utf-8")
        assert _check(scan(root), "L0_any_instrumentation").verdict != "fail", body
