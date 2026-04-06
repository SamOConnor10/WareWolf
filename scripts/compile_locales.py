#!/usr/bin/env python
"""Compile locale/*/LC_MESSAGES/django.po to .mo (requires: python -m pip install polib)."""
import sys
from pathlib import Path

try:
    import polib
except ImportError:
    print("Install polib: python -m pip install polib", file=sys.stderr)
    sys.exit(1)

root = Path(__file__).resolve().parents[1]
for po_path in root.glob("locale/*/LC_MESSAGES/django.po"):
    po = polib.pofile(str(po_path), encoding="utf-8")
    mo_path = po_path.with_suffix(".mo")
    po.save_as_mofile(str(mo_path))
    print(f"Compiled {po_path.relative_to(root)} -> {mo_path.relative_to(root)} ({len(po)} entries)")
