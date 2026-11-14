"""`python -m factory demo`: the LLM-free part of the story in under ~2 minutes:
calibrate (pristine vs real vanilla) -> selftest (verifier vs fixes, traps, cheating patches) -> report (replays of real runs).
"""
from __future__ import annotations

import os
import time

from . import calibrate, selftest, util


def main(argv) -> int:
    t0 = time.time()
    print("== 1/3 calibrate: pristine simulator vs every real vanilla trace available")
    cal = calibrate.run(verbose=True)
    print("\n== 2/3 selftest: the verifier on reference fixes, naive (trap) fixes and adversarial patches (scripted, no LLM)")
    st = selftest.run(verbose=True)
    print("\n== 3/3 report")
    from . import report
    report.main([])
    out = util.ROOT / "report" / "index.html"
    print(f"\ndemo done in {time.time() - t0:.0f}s: calibration {cal['corpus_matched']}/{len(cal['corpus'])} corpus + "
          f"{cal['dev_goldens_matched']}/{len(cal['dev_goldens'])} dev goldens match; selftest {st['passed']}/{st['total']}; "
          f"report: {out}")
    if "--no-open" not in argv and os.name == "nt":
        os.startfile(out)  # noqa: S606 (opens the local report in the default browser)
    return 0 if st["passed"] == st["total"] else 1
