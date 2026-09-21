"""Serialized analyzer worker entrypoint; no API or persistence imports."""

from __future__ import annotations

import argparse
import sys
from contextlib import redirect_stdout

from ..contracts.requests import canonical_json
from ..contracts.results import AnalyzerInput, CategoryResult
from .registry import canonical_registry, register_default_factories


def run_serialized(payload: str | bytes, *, analyzer_id: str) -> str:
    register_default_factories()
    analyzer_input = AnalyzerInput.model_validate_json(payload)
    result = canonical_registry.run(analyzer_id, analyzer_input)
    return canonical_json(CategoryResult.model_validate(result.model_dump(mode="json")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analyzer", required=True)
    args = parser.parse_args(argv)
    with redirect_stdout(sys.stderr):
        output = run_serialized(sys.stdin.buffer.read(), analyzer_id=args.analyzer)
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_serialized"]
