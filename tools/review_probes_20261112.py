"""Rerun both audit rounds, inventory reconciliation and launcher regressions."""
from pathlib import Path
import sys
import unittest

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(root / 'tests')]
suite = unittest.TestSuite()
loader = unittest.TestLoader()
for pattern in ('test_review_fixes.py', 'test_inventory_audit.py', 'test_project_review.py', 'test_bundle_runtime.py'):
    suite.addTests(loader.discover(str(root / 'tests'), pattern=pattern))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
