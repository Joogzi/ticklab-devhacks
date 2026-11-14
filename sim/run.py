"""Convenience launcher (works from any directory):

  python sim/run.py sim <scenario.json> [--out trace.jsonl]   # run the simulator
  python sim/run.py test                                        # run the unit tests
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))
sys.dont_write_bytecode = True


def main(argv) -> int:
    if not argv or argv[0] not in ("sim", "test"):
        print(__doc__)
        return 2
    if argv[0] == "test":
        suite = unittest.defaultTestLoader.discover(str(HERE / "tests"), top_level_dir=str(HERE / "tests"))
        res = unittest.TextTestRunner(verbosity=1).run(suite)
        return 0 if res.wasSuccessful() else 1
    from mcsim.main import main as sim_main
    return sim_main(["run"] + argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
