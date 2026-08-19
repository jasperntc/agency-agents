#!/usr/bin/env python3
"""run_suite.py -- import one generated module and run one acceptance suite.

    python3 -I scripts/lib/run_suite.py <artifact.py> <suite.py>

Prints a single JSON object to stdout and nothing else.

THIS IS THE ONLY PLACE IN THE REPOSITORY THAT IMPORTS MODEL-GENERATED CODE.

It is a separate process on purpose. An artifact that loops forever, exhausts
memory, or raises at import time takes this process down and not the harness,
and the harness records that outcome as the result rather than crashing with
it. The caller runs it with a wall-clock timeout, a scratch working directory,
and -I so the repository is not on sys.path.

What this does NOT do is sandbox. A generated module can still open sockets and
write files. That is why scripts/eval_construction.py --execute is a local,
opt-in command and never runs in CI: the artifacts are committed and reviewable
in a diff first, and CI only ever re-scores the results this produced.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from pathlib import Path


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def brief(exc: BaseException, limit: int = 400) -> str:
    """One line of what went wrong, truncated -- a traceback is not a result."""
    text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    text = " ".join(text.split())
    return text[:limit]


def main(argv: list[str]) -> int:
    artifact, suite_path = Path(argv[1]), Path(argv[2])
    suite = load(suite_path, "acceptance_suite")
    checks = suite.CHECKS

    try:
        module = load(artifact, "artifact_under_test")
    except BaseException as exc:  # noqa: BLE001 -- SystemExit counts as a failure
        # Every check fails, and it fails for ONE stated reason. Reporting the
        # import error against each check separately would read as six
        # independent engineering mistakes instead of one file that does not
        # load.
        print(json.dumps({
            "import_error": brief(exc),
            "checks": {c["id"]: {"ok": False, "error": "module did not import"}
                       for c in checks},
        }))
        return 0

    results = {}
    for check in checks:
        fn = getattr(suite, f"check_{check['id']}", None)
        if fn is None:
            results[check["id"]] = {"ok": False, "error": "suite has no such check"}
            continue
        try:
            fn(module)
            results[check["id"]] = {"ok": True, "error": None}
        except BaseException as exc:  # noqa: BLE001
            results[check["id"]] = {"ok": False, "error": brief(exc)}

    print(json.dumps({"import_error": None, "checks": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
