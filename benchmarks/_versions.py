"""Version metadata for benchmark reports.

Every benchmark report records the stele version it ran under (plus the
upstream summary/index/graph deps, since their versions move the numbers).
Lets a committed run under `benchmarks/runs/<date>/` be traced back to the
exact package set that produced it.
"""

from __future__ import annotations

import importlib.metadata as _metadata

# stele-core is the headline; lede/chunkshop/pg-raggraph shape summary,
# indexing, and graph retrieval respectively, so a number is only meaningful
# alongside their versions.
_PACKAGES = ("stele-core", "lede", "chunkshop", "pg-raggraph")


def stele_version() -> str:
    try:
        return _metadata.version("stele-core")
    except _metadata.PackageNotFoundError:
        return "unknown"


def version_info() -> dict[str, str]:
    """Map of package name -> installed version (``"not-installed"`` if absent)."""
    out: dict[str, str] = {}
    for name in _PACKAGES:
        try:
            out[name] = _metadata.version(name)
        except _metadata.PackageNotFoundError:
            out[name] = "not-installed"
    return out


def versions_md_line() -> str:
    """One-line Markdown summary of the recorded versions."""
    return "  ·  ".join(f"{name} `{ver}`" for name, ver in version_info().items())
