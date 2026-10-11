#!/usr/bin/env python3
"""upd_check_tag_version.py — verify that a wheel file's version matches a git tag.

Usage::

    python scripts/upd_check_tag_version.py <tag> <wheel_path>

Arguments:

- *tag*: git tag string (e.g., ``v0.23.1.post2``)
- *wheel_path*: path to a built wheel file
  (e.g., ``dist/mcp_atlassian-0.23.1.post2-py3-none-any.whl``)

Exit codes:

- 0  wheel version matches the tag version
- 1  version mismatch, file not found, METADATA not found, or parse error
"""

import argparse
import sys
import zipfile
from io import TextIOWrapper
from pathlib import Path


def strip_v_prefix(tag: str) -> str:
    """Remove leading 'v' from a tag.

    >>> strip_v_prefix('v0.23.1.post2')
    '0.23.1.post2'
    >>> strip_v_prefix('0.23.1.post2')
    '0.23.1.post2'
    >>> strip_v_prefix('v1.0.0')
    '1.0.0'
    """
    return tag.lstrip("v")


def extract_version_from_metadata(metadata_text: str) -> str | None:
    """Extract version from wheel METADATA content.

    Searches for a line starting with ``Version: `` and returns the value.
    Returns ``None`` if not found.

    >>> extract_version_from_metadata('Name: foo\\nVersion: 1.2.3\\nSummary: bar\\n')
    '1.2.3'
    >>> extract_version_from_metadata('Name: foo\\nSummary: bar\\n') is None
    True
    >>> extract_version_from_metadata('Version: 0.23.1.post2\\n')
    '0.23.1.post2'
    """
    for line in metadata_text.splitlines():
        if line.startswith("Version: "):
            return line[len("Version: ") :].strip()
    return None


def check_version_match(tag: str, wheel_version: str) -> bool:
    """Check if tag version matches wheel version after stripping 'v' prefix.

    >>> check_version_match('v0.23.1.post2', '0.23.1.post2')
    True
    >>> check_version_match('v0.23.1.post2', '0.23.1.post1')
    False
    >>> check_version_match('v1.0.0', '1.0.0')
    True
    """
    expected = strip_v_prefix(tag)
    return expected == wheel_version


def read_metadata_from_wheel(wheel_path: Path) -> str | None:
    """Read METADATA file from a wheel (ZIP archive).

    Returns the METADATA content as a string, or ``None`` if not found.
    Raises ``FileNotFoundError`` if the wheel file doesn't exist.
    Raises ``zipfile.BadZipFile`` if the wheel is not a valid ZIP.
    """
    if not wheel_path.exists():
        msg = f"Wheel file not found: {wheel_path}"
        raise FileNotFoundError(msg)

    try:
        with zipfile.ZipFile(wheel_path, "r") as whl:
            # Find the .dist-info directory
            dist_info_dirs = [
                name for name in whl.namelist() if ".dist-info/" in name
            ]
            if not dist_info_dirs:
                return None

            # Find METADATA in one of the .dist-info dirs
            for file_path in whl.namelist():
                if file_path.endswith(".dist-info/METADATA"):
                    with whl.open(file_path) as metadata_file:
                        return TextIOWrapper(metadata_file, encoding="utf-8").read()

            return None
    except zipfile.BadZipFile as exc:
        msg = f"Wheel file is not a valid ZIP: {wheel_path}"
        raise zipfile.BadZipFile(msg) from exc


def _run_check(tag: str, wheel_version: str) -> int:
    """Check version match and return exit code.

    Returns 0 if versions match, 1 if they don't.

    >>> _run_check('v0.23.1.post2', '0.23.1.post2')
    0
    >>> _run_check('v0.23.1.post2', '0.23.1.post1')
    1
    """
    if check_version_match(tag, wheel_version):
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Verify that a wheel file's version matches a git tag."
    )
    parser.add_argument("tag", help="Git tag (e.g., v0.23.1.post2)")
    parser.add_argument("wheel_path", help="Path to wheel file")
    args = parser.parse_args(argv)

    wheel_path = Path(args.wheel_path)

    # Check if wheel exists
    if not wheel_path.exists():
        print(
            f"ERROR: wheel file not found: {wheel_path}",
            file=sys.stderr,
        )
        return 1

    # Try to read METADATA from wheel
    try:
        metadata_text = read_metadata_from_wheel(wheel_path)
    except (zipfile.BadZipFile, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if metadata_text is None:
        print(
            f"ERROR: METADATA not found in wheel: {wheel_path}",
            file=sys.stderr,
        )
        return 1

    # Extract version from METADATA
    wheel_version = extract_version_from_metadata(metadata_text)
    if wheel_version is None:
        print(
            "ERROR: Version header not found in METADATA",
            file=sys.stderr,
        )
        return 1

    # Check if versions match
    expected_version = strip_v_prefix(args.tag)
    if not check_version_match(args.tag, wheel_version):
        print(
            f"ERROR: version mismatch: tag={expected_version}, "
            f"wheel={wheel_version}",
            file=sys.stderr,
        )
        return 1

    # Success
    print(f"OK: {args.tag} matches wheel version {wheel_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
