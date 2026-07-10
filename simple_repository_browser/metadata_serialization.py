"""Serialize PackageInfo into the JSON shape stored in projects.metadata_json.

The `dependencies_idx` triggers in `fetch_projects` expect
`$.requires_dist` to be a JSON array of objects with keys
`name`, `extra`, `specifier`, `marker`.
"""

from __future__ import annotations

import json

from packaging.utils import canonicalize_name

from .fetch_description import PackageInfo, Requirement, RequirementsSequence


def _dep_entries(req: Requirement) -> list[dict]:
    """Return one entry per extra the requirement is scoped to (empty extras → single core entry)."""
    marker = str(req.marker) if req.marker is not None else None
    specifier = str(req.specifier)
    name = canonicalize_name(req.name)
    extras = RequirementsSequence.extras_for_requirement(req)
    if not extras:
        return [{"name": name, "extra": None, "specifier": specifier, "marker": marker}]
    return [
        {"name": name, "extra": extra, "specifier": specifier, "marker": marker}
        for extra in sorted(extras)
    ]


def pkg_info_to_metadata_json(
    pkg_info: PackageInfo, *, source: str | None = None
) -> str:
    deps: list[dict] = []
    for req in pkg_info.requires_dist:
        if not isinstance(req, Requirement):
            continue
        deps.extend(_dep_entries(req))
    return json.dumps(
        {
            "requires_dist": deps,
            "project_urls": dict(pkg_info.project_urls),
            "source": source.lower() if source else None,
        }
    )
