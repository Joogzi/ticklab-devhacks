"""`python -m factory report`: build report/index.html (see viewer/build_report.py)."""
import sys

from . import util

sys.path.insert(0, str(util.ROOT / "viewer"))


def main(argv) -> int:
    import build_report
    return build_report.main(argv)
