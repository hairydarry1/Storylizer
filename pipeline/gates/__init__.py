"""Quality gates (BUILD_SPEC.md section 7).

M5 builds `ledger_check`; `linter`, `rubric` and `originality` arrive with M7 and M8.
"""

from . import ledger_check

__all__ = ["ledger_check"]
