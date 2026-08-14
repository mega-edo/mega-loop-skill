"""Grade a developer's traces against the contract MEGA Loop actually enforces.

The public surface is deliberately small: normalize spans, grade them, render the result.
`contract.py` is where upstream's rules live and the only file that should change when
`mega-loop` changes.
"""

from __future__ import annotations

from trace_validator.checks import (
    Check,
    SampleGrade,
    TraceGrade,
    grade,
    grade_sample,
    group_by_trace,
)
from trace_validator.span import Span, normalize

__all__ = [
    "Check",
    "SampleGrade",
    "Span",
    "TraceGrade",
    "grade",
    "grade_sample",
    "group_by_trace",
    "normalize",
]

__version__ = "0.1.0"
