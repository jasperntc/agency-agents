#!/usr/bin/env python3
"""Tests for the canonical frontmatter parser and the agent schema.

Run against the REAL corpus rather than fixtures. A schema that only validates
invented examples proves nothing about the 270 files that actually ship.

    python3 tests/test_frontmatter.py

Requires requirements-dev.txt (PyYAML, jsonschema).
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import yaml  # noqa: E402

from lib.corpus import read_corpus  # noqa: E402
from lib.frontmatter import (  # noqa: E402
    FrontmatterError, compat_get_field, divergence_report, load_schema, parse,
    validate,
)

# Divergence causes we have explained. Anything else is a NEW finding and should
# fail, because an unclassified disagreement between the canonical parser and
# the distribution layer is exactly what this module exists to surface.
EXPLAINED_KINDS = {"quotes-not-stripped", "block-value"}

_paths: list[str] = []
_parsed: dict[str, tuple[dict, str, bytes]] = {}
_schema: dict = {}


def setUpModule() -> None:
    global _schema
    _schema = load_schema()
    _paths.extend(sorted(read_corpus(None)))
    for p in _paths:
        _parsed[p] = parse(p)


class TestParsing(unittest.TestCase):
    def test_every_agent_parses_as_yaml(self):
        """All 270 must parse. Step 0.4b was a prerequisite: before it, a
        description containing ': ' was a hard YAML error."""
        self.assertEqual(len(_parsed), len(_paths))
        self.assertGreater(len(_paths), 0, "no agents found")

    def test_frontmatter_is_always_a_mapping(self):
        for p in _paths:
            with self.subTest(agent=p):
                self.assertIsInstance(_parsed[p][0], dict)

    def test_body_is_never_empty(self):
        for p in _paths:
            with self.subTest(agent=p):
                self.assertTrue(_parsed[p][1].strip(), "empty body")

    def test_missing_fence_is_an_error(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as fh:
            fh.write("no frontmatter here\n")
            tmp = fh.name
        try:
            with self.assertRaises(FrontmatterError):
                parse(tmp)
        finally:
            Path(tmp).unlink()


class TestSchema(unittest.TestCase):
    def test_every_agent_validates(self):
        """Zero violations across the corpus.

        If this fails, do NOT loosen the schema to make it pass -- the schema
        was derived from the corpus, so a violation means either a real defect
        in a file or a real change in the contract. Both need a decision.
        """
        violations = {}
        for p in _paths:
            errs = validate(_parsed[p][0], _schema)
            if errs:
                violations[p] = errs
        self.assertEqual(violations, {}, f"{len(violations)} agent(s) violate the schema")

    def test_required_fields_are_enforced(self):
        for field in ("name", "description", "color"):
            with self.subTest(field=field):
                fm = {"name": "X", "description": "Y", "color": "blue"}
                del fm[field]
                self.assertTrue(validate(fm, _schema), f"missing {field} should fail")

    def test_unknown_field_is_rejected(self):
        fm = {"name": "X", "description": "Y", "color": "blue", "surprise": "z"}
        self.assertTrue(validate(fm, _schema),
                        "additionalProperties should reject unknown fields")

    def test_name_may_not_have_surrounding_whitespace(self):
        """Guards the defect Step 0.4a repaired: aligned frontmatter made
        get_field return '       Clinical Evidence Agent'."""
        fm = {"name": "   Padded Name", "description": "Y", "color": "blue"}
        self.assertTrue(validate(fm, _schema))

    def test_services_shape_is_enforced(self):
        ok = {"name": "X", "description": "Y", "color": "blue",
              "services": [{"name": "S", "url": "https://e.com", "tier": "free"}]}
        self.assertEqual(validate(ok, _schema), [])
        bad = {"name": "X", "description": "Y", "color": "blue",
               "services": [{"name": "S", "url": "https://e.com", "tier": "cheap"}]}
        self.assertTrue(validate(bad, _schema), "tier must be free|freemium|paid")


class TestLegacyDivergence(unittest.TestCase):
    def test_compat_matches_real_bash(self):
        """compat_get_field must reproduce scripts/lib.sh exactly.

        The whole divergence report rests on this reimplementation being
        faithful, so it is checked against the actual shell function rather
        than assumed. Sampled, because each call spawns a process.
        """
        sample = _paths[::37]
        script = (
            f'. "{REPO_ROOT}/scripts/lib.sh"; '
            'for f in "$@"; do for k in name description color emoji vibe tools; do '
            'printf "%s\\t%s\\t%s\\n" "$f" "$k" "$(get_field "$k" "$f")"; done; done'
        )
        proc = subprocess.run(["bash", "-c", script, "_", *sample],
                              cwd=REPO_ROOT, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))

        checked = 0
        for line in proc.stdout.decode("utf-8").split("\n"):
            if not line.strip():
                continue
            path, key, shell_value = line.split("\t", 2)
            raw = Path(REPO_ROOT / path).read_bytes()
            with self.subTest(agent=path, field=key):
                self.assertEqual(compat_get_field(raw, key), shell_value)
            checked += 1
        self.assertGreater(checked, 0, "no fields compared")

    def test_all_divergence_is_explained(self):
        """Every disagreement must have a known cause.

        An unclassified divergence means the distribution layer is reading
        something in a way nobody has accounted for.
        """
        unexplained = []
        for p in _paths:
            for d in divergence_report(p):
                if d["kind"] not in EXPLAINED_KINDS:
                    unexplained.append((p, d["field"], d["kind"], d["legacy"]))
        self.assertEqual(unexplained, [], "unexplained parser divergence")

    def test_services_is_invisible_to_the_legacy_reader(self):
        """Documents the dead field: 4 agents declare `services`, and no
        converter can see it, because get_field cannot read a block value."""
        found = 0
        for p in _paths:
            fm, _, raw = _parsed[p]
            if "services" in fm:
                found += 1
                self.assertIsInstance(fm["services"], list)
                self.assertEqual(compat_get_field(raw, "services"), "")
        self.assertGreater(found, 0, "expected at least one agent with services")


class TestRoundTrip(unittest.TestCase):
    def test_parse_emit_parse_is_stable(self):
        """Re-emitting through YAML and re-parsing must yield identical data.

        Guards the Phase 3 `id` migration, which rewrites frontmatter across all
        270 files: if a round trip is lossy, that migration is unsafe.
        """
        for p in _paths:
            fm = _parsed[p][0]
            with self.subTest(agent=p):
                again = yaml.safe_load(yaml.safe_dump(fm, allow_unicode=True,
                                                      sort_keys=False))
                self.assertEqual(again, fm)


if __name__ == "__main__":
    unittest.main(verbosity=2)
