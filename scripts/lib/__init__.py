"""Python helpers for the skill engineering layer.

Distinct from scripts/lib.sh, which holds the bash helpers used by the
distribution layer (convert.sh, install.sh). Nothing here may become a runtime
dependency of the install path -- that path stays bash 3.2 + no jq.
"""
