#!/usr/bin/env python3
"""upd_check_junit.py — validate a pytest JUnit XML against a known-failures list.

Usage::

    python scripts/upd_check_junit.py <junit_xml> <known_failures> --pytest-rc <N>

Exit codes:

- 0  all failures are in the known-failure list (or there are none)
- 1  unexpected failure, collection error, malformed XML, or invalid rc
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def check_rc(rc: int) -> bool:
    """Return True if *rc* is an acceptable pytest exit code (0 or 1).

    >>> check_rc(0)
    True
    >>> check_rc(1)
    True
    >>> check_rc(2)
    False
    """
    return rc in (0, 1)


def load_known_failures(text: str) -> set[str]:
    """Parse a known-failures file and return the set of test IDs.

    Lines starting with ``#`` and blank lines are ignored.

    >>> sorted(load_known_failures("# comment\\na::b\\n\\nc::d"))
    ['a::b', 'c::d']
    >>> load_known_failures("")
    set()
    """
    result: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            result.add(stripped)
    return result


def get_testcases(xml_content: str) -> tuple[list, str | None]:
    """Parse *xml_content* and return ``(testcases, error_msg)``.

    *error_msg* is ``None`` on success; a non-empty string describes the problem.

    Empty content → error:

    >>> _, err = get_testcases("")
    >>> err is not None
    True

    Zero ``<testcase>`` elements → error:

    >>> _, err = get_testcases('<testsuite tests="0"></testsuite>')
    >>> err is not None
    True

    Collection error (``<error>`` child) → error:

    >>> xml = ('<testsuites><testsuite tests="1">'
    ...        '<testcase classname="c" name="err"><error message="boom"/></testcase>'
    ...        '</testsuite></testsuites>')
    >>> _, err = get_testcases(xml)
    >>> err is not None
    True

    Valid XML with one testcase → success:

    >>> xml = ('<testsuites><testsuite tests="1">'
    ...        '<testcase classname="a" name="b"><failure/></testcase>'
    ...        '</testsuite></testsuites>')
    >>> cases, err = get_testcases(xml)
    >>> err is None
    True
    >>> len(cases)
    1
    """
    if not xml_content.strip():
        return [], "junit XML is empty"
    try:
        root = ET.fromstring(xml_content)  # noqa: S314
    except ET.ParseError as exc:
        return [], f"junit XML is not valid XML: {exc}"

    testcases = root.findall(".//testcase")
    if not testcases:
        return [], "0 tests collected (no <testcase> elements)"

    for tc in testcases:
        if tc.find("error") is not None:
            classname = tc.get("classname", "")
            name = tc.get("name", "")
            test_id = f"{classname}::{name}" if classname else name
            return [], f"collection error in testcase: {test_id}"

    return testcases, None


def analyze_junit(xml_content: str, known_failures: set[str]) -> tuple[int, list[str]]:
    """Check a junit XML string against *known_failures*.

    Returns ``(exit_code, messages)`` where *exit_code* is 0 or 1.

    Case 1 — unexpected failure → exit 1:

    >>> xml = ('<testsuites><testsuite tests="1">'
    ...        '<testcase classname="a" name="b"><failure/></testcase>'
    ...        '</testsuite></testsuites>')
    >>> code, msgs = analyze_junit(xml, set())
    >>> code
    1
    >>> any("UNEXPECTED" in m for m in msgs)
    True

    Case 2 — listed failure → exit 0:

    >>> code, msgs = analyze_junit(xml, {"a::b"})
    >>> code
    0

    Case 3 — known failure now passing → warning, exit 0:

    >>> xml_pass = ('<testsuites><testsuite tests="1">'
    ...             '<testcase classname="a" name="b"/>'
    ...             '</testsuite></testsuites>')
    >>> code, msgs = analyze_junit(xml_pass, {"a::b"})
    >>> code
    0
    >>> any("KNOWN-FAILURE-NOW-PASSING" in m for m in msgs)
    True
    """
    testcases, err = get_testcases(xml_content)
    if err is not None:
        return 1, [f"ERROR: {err}"]

    messages: list[str] = []
    exit_code = 0
    all_ids: set[str] = set()
    failed_ids: set[str] = set()

    for tc in testcases:
        classname = tc.get("classname", "")
        name = tc.get("name", "")
        test_id = f"{classname}::{name}" if classname else name

        # Skipped tests are neither passed nor failed
        if tc.find("skipped") is not None:
            continue

        all_ids.add(test_id)

        if tc.find("failure") is not None:
            failed_ids.add(test_id)
            if test_id not in known_failures:
                messages.append(f"UNEXPECTED FAILURE: {test_id}")
                exit_code = 1

    for kf in known_failures:
        if kf in all_ids and kf not in failed_ids:
            messages.append(f"KNOWN-FAILURE-NOW-PASSING: {kf}")

    return exit_code, messages


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Validate pytest JUnit XML against a known-failures list."
    )
    parser.add_argument("junit_xml", help="Path to junit.xml produced by pytest")
    parser.add_argument("known_failures", help="Path to known-failures file")
    parser.add_argument(
        "--pytest-rc",
        type=int,
        required=True,
        dest="pytest_rc",
        help="The pytest exit code",
    )
    args = parser.parse_args(argv)

    if not check_rc(args.pytest_rc):
        print(
            f"ERROR: --pytest-rc {args.pytest_rc} is not valid (expected 0 or 1)",
            file=sys.stderr,
        )
        return 1

    junit_path = Path(args.junit_xml)
    if not junit_path.exists():
        print(f"ERROR: junit XML not found: {junit_path}", file=sys.stderr)
        return 1

    xml_content = junit_path.read_text(encoding="utf-8")

    kf_path = Path(args.known_failures)
    kf_text = kf_path.read_text(encoding="utf-8") if kf_path.exists() else ""
    known_failures = load_known_failures(kf_text)

    exit_code, messages = analyze_junit(xml_content, known_failures)
    for msg in messages:
        print(msg)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
