"""Image-owned framework launcher. Reporting is separate from test stdout/stderr."""

import json
import os
import sys
import unittest


def unit(target):
    sys.path.insert(0, "/workspace")
    if os.path.isfile(target):
        suite = unittest.defaultTestLoader.discover(
            os.path.dirname(target) or ".", pattern=os.path.basename(target)
        )
    else:
        suite = unittest.defaultTestLoader.discover(target)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return (0 if result.wasSuccessful() else 1), {
        "executed": result.testsRun - len(result.skipped),
        "skipped": len(result.skipped),
        "failed": len(result.failures) + len(result.errors) + len(result.unexpectedSuccesses),
    }


def pytest_run(target):
    try:
        import pytest
    except ImportError:
        return 127, {"unavailable": True}

    class Reports:
        executed = 0
        skipped = 0
        failed = 0

        def pytest_runtest_logreport(self, report):
            if report.skipped:
                self.skipped += 1
            if report.when == "call" and not report.skipped:
                self.executed += 1
            if report.failed:
                self.failed += 1

    reports = Reports()
    code = int(pytest.main([target, "-q"], plugins=[reports]))
    return code, {key: getattr(reports, key) for key in ("executed", "skipped", "failed")}


if __name__ == "__main__":
    profile, target, fd = sys.argv[1:]
    try:
        code, report = unit(target) if profile == "unittest" else pytest_run(target)
    except BaseException:
        code, report = 2, {"unavailable": True}
    report.update(version=1, profile=profile)
    with os.fdopen(int(fd), "w", encoding="utf-8") as output:
        json.dump(report, output)
    raise SystemExit(code)
