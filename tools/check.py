"""Development and CI validation: run the whole test suite and report the
result readably.

    python tools/check.py                 # run, print a short report
    python tools/check.py --log FILE      # also keep the full output there

This is the gate for builds that are handed to other people (``build.py
--release``, CI). It is **not** part of an ordinary install: a user building
EqUpdater for themselves should not be blocked by a GUI or timing test that
behaves differently on their PC.

**Why the suite runs in a child process.** Some failures are not exceptions:
Tcl aborts the whole process when a Tk interpreter is freed on the wrong
thread, with no traceback at all. In a child process started with
``-X faulthandler``, the parent survives that, knows which test was running
(the verbose output names each test before it runs), and can show the stack
of every thread at the moment of the crash.

On success it prints one line. On failure it prints each failing test's name,
exception and traceback -- not the whole run -- and says where the full log is.

Exit status: 0 when every test passed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_REPORT_LINES = 250

_RESULT = re.compile(r"^(?P<test>\S+ \([\w.]+\)) \.\.\. ")
_OUTCOME = re.compile(r"\.\.\. (ok|FAIL|ERROR|skipped.*|expected failure|"
                      r"unexpected success)\s*$")


def run_suite(log_path: str | None = None) -> tuple[bool, str]:
    """Run the suite; return (passed, short report)."""
    cmd = [sys.executable, "-X", "faulthandler", "-m", "unittest",
           "discover", "-v", "-s", os.path.join(ROOT, "tests"), "-t", ROOT]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    output = (proc.stdout or "") + (proc.stderr or "")

    if log_path:
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("$ " + " ".join(cmd) + "\n\n" + output)

    lines = output.splitlines()
    ran = next((l for l in lines if l.startswith("Ran ")), None)
    finished = ran is not None
    passed = proc.returncode == 0 and finished and any(
        l.startswith("OK") for l in lines)

    if passed:
        return True, "%s -- all passed" % ran.rstrip(".")

    report = []
    where = f" (full log: {log_path})" if log_path else ""
    if not finished:
        # The process died mid-run. The last "test ... " line without an
        # outcome is the test that was running.
        running = None
        for line in lines:
            m = _RESULT.match(line)
            if m and not _OUTCOME.search(line):
                running = m.group("test")
            elif m:
                running = None
        report.append("The test process crashed (exit code %s)%s."
                      % (proc.returncode, where))
        if running:
            report.append("It was running: " + running)
        report.append("")
        crash = [l for l in lines if "Fatal Python error" in l
                 or "Tcl_" in l or "fatal exception" in l]
        report.extend(crash[:10])
        # faulthandler's per-thread stacks follow the fatal line.
        start = next((i for i, l in enumerate(lines)
                      if l.startswith(("Current thread", "Thread 0x"))), None)
        if start is not None:
            report.append("")
            report.extend(lines[start:start + 80])
    else:
        failing = [l for l in lines if l.startswith(("FAIL: ", "ERROR: "))]
        report.append("%d test(s) failed%s:" % (len(failing), where))
        report.extend("  " + l for l in failing)
        report.append("")
        # unittest's failure section: from the first ===== line to "Ran N".
        start = next((i for i, l in enumerate(lines) if l.startswith("=" * 20)),
                     None)
        end = lines.index(ran) if ran in lines else len(lines)
        if start is not None:
            report.extend(lines[start:end])

    if len(report) > MAX_REPORT_LINES:
        report = report[:MAX_REPORT_LINES] + [
            "... (%d more lines in the log)" % (len(report) - MAX_REPORT_LINES)]
    return False, "\n".join(report)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--log", help="write the complete test output here")
    args = ap.parse_args()
    passed, report = run_suite(args.log)
    print(report)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
