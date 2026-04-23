#!/usr/bin/env python3
"""Generate catalog.json from app TOML files.

Reads catalog.toml for metadata, integrations.toml for the
integration vocabulary, and apps/*/app.toml for each app entry.
Emits catalog.json in the openhost.catalog.v1 feed format.

Usage:
    generate.py           # Write catalog.json
    generate.py --check   # Exit non-zero if catalog.json is stale; don't write
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

# App names must be lowercase alphanumeric with optional interior hyphens.
# This matches OpenHost's app_name validation.
_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

# Python 3.11+ has tomllib; fall back to tomli for older versions
try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        print(
            "error: need Python 3.11+ (tomllib) or 'pip install tomli'", file=sys.stderr
        )
        sys.exit(1)


def load_toml(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_integrations(root: str) -> dict[str, dict]:
    """Load the integration vocabulary from integrations.toml.

    Returns a dict keyed by integration id (e.g. 'zone_owner_auto_login')
    with the full toml entry for each. generate.py uses this to:
      * validate that every key referenced in an app.toml exists,
      * emit human-readable title + description into catalog.json.
    """
    path = os.path.join(root, "integrations.toml")
    if not os.path.isfile(path):
        return {}
    raw = load_toml(path)
    # Filter out non-table top-level entries defensively.
    return {k: v for k, v in raw.items() if isinstance(v, dict)}


def validate_integration(app_toml_path: str, app: dict, vocab: dict[str, dict]) -> dict:
    """Validate + normalise an app's [integration] table.

    Exits non-zero with a clear message if anything is malformed.
    Returns the normalised integration dict, ready to embed in
    catalog.json. Apps without an [integration] table get a default
    level-1 entry so the UI always has something to render.
    """
    integ = app.get("integration")
    if integ is None:
        # Default for unmigrated apps: level 1, every integration missing.
        return {
            "level": 1,
            "summary": "",
            "has": [],
            "missing": list(vocab.keys()),
            "not_applicable": [],
        }

    def fail(msg: str) -> None:
        print(f"error: {app_toml_path}: {msg}", file=sys.stderr)
        sys.exit(1)

    level = integ.get("level")
    if not isinstance(level, int) or level < 1 or level > 5:
        fail("[integration].level must be an integer 1-5")

    has = list(integ.get("has", []) or [])
    missing = list(integ.get("missing", []) or [])
    not_applicable = list(integ.get("not_applicable", []) or [])
    summary = str(integ.get("summary", "") or "")

    seen: dict[str, str] = {}
    for bucket_name, bucket in (
        ("has", has),
        ("missing", missing),
        ("not_applicable", not_applicable),
    ):
        for key in bucket:
            if not isinstance(key, str):
                fail(f"[integration].{bucket_name} entries must be strings; got {key!r}")
            if key not in vocab:
                fail(
                    f"[integration].{bucket_name} references unknown key {key!r}. "
                    "Add it to integrations.toml or remove it."
                )
            if key in seen:
                fail(
                    f"integration key {key!r} appears in both "
                    f"{seen[key]} and {bucket_name}; each key may appear at "
                    "most once across has/missing/not_applicable."
                )
            seen[key] = bucket_name

    # Level 5 means "nothing to improve", so missing must be empty.
    if level == 5 and missing:
        fail(
            "[integration].level = 5 but missing is non-empty. Either resolve "
            f"the gaps ({', '.join(missing)}) or lower the level."
        )

    return {
        "level": level,
        "summary": summary,
        "has": has,
        "missing": missing,
        "not_applicable": not_applicable,
    }


def build_feed(root: str) -> dict:
    """Build the feed dict (excluding generated_at) from the source TOML files."""
    catalog_path = os.path.join(root, "catalog.toml")
    catalog = load_toml(catalog_path).get("catalog", {})

    source_id = catalog.get("source_id", "official")
    source_name = catalog.get("name", "OpenHost Official")

    vocab = load_integrations(root)

    apps_dir = os.path.join(root, "apps")
    apps: list[dict] = []

    for entry in sorted(os.listdir(apps_dir)):
        app_toml = os.path.join(apps_dir, entry, "app.toml")
        if not os.path.isfile(app_toml):
            continue

        data = load_toml(app_toml)
        app = data.get("app", {})

        name = app.get("name", "")
        if not name:
            print(
                f"error: {app_toml}: missing required [app].name field",
                file=sys.stderr,
            )
            sys.exit(1)
        if not _NAME_PATTERN.match(name):
            print(
                f"error: {app_toml}: invalid [app].name {name!r}; "
                "must be lowercase alphanumeric with optional interior hyphens",
                file=sys.stderr,
            )
            sys.exit(1)
        if not app.get("repo_url"):
            print(
                f"error: {app_toml}: missing required [app].repo_url field",
                file=sys.stderr,
            )
            sys.exit(1)

        integration = validate_integration(app_toml, data, vocab)

        feed_app = {
            "name": name,
            "title": app.get("title", name),
            "description": app.get("description", ""),
            "repo_url": app["repo_url"],
            "repo_ref": app.get("repo_ref", ""),
            "icon_url": app.get("icon_url", ""),
            "tags": app.get("tags", []),
            "categories": app.get("categories", []),
            "website_url": app.get("website_url", ""),
            "docs_url": app.get("docs_url", ""),
            "integration": integration,
        }

        apps.append(feed_app)

    # Each app's `name` is the identifier the catalog uses for URLs, DB keys,
    # and the default deployed app name. Within a single source, names must be
    # unique; otherwise the catalog sync rejects the feed entirely.
    seen_names: dict[str, int] = {}
    for i, app in enumerate(apps):
        name = app["name"]
        if name in seen_names:
            first = apps[seen_names[name]]["title"]
            print(
                f"error: duplicate name {name!r} (first seen in {first!r}); "
                "each app in a source must have a unique name",
                file=sys.stderr,
            )
            sys.exit(1)
        seen_names[name] = i

    feed = {
        "schema": "openhost.catalog.v1",
        "source_id": source_id,
        "source_name": source_name,
        "apps": apps,
    }
    if vocab:
        # Emit the vocabulary alongside the apps so the catalog UI
        # can render titles + descriptions without having to pull a
        # second file from the source.
        feed["integrations"] = {
            key: {
                "title": entry.get("title", key),
                "description": entry.get("description", ""),
            }
            for key, entry in vocab.items()
        }
    return feed


def stable_copy(feed: dict) -> dict:
    """Return a copy of the feed with generated_at stripped, for comparisons."""
    return {k: v for k, v in feed.items() if k != "generated_at"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate catalog.json")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if catalog.json does not match the source TOML files. Does not write.",
    )
    args = parser.parse_args()

    root = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(root, "catalog.json")

    feed = build_feed(root)
    fresh_stable = stable_copy(feed)

    if args.check:
        try:
            with open(output_path) as f:
                committed = json.load(f)
        except FileNotFoundError:
            print(
                f"error: {output_path} does not exist. Run `python3 generate.py`.",
                file=sys.stderr,
            )
            return 1
        if stable_copy(committed) != fresh_stable:
            print(
                f"error: {output_path} is stale. Run `python3 generate.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"{output_path} is up to date")
        return 0

    feed["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(output_path, "w") as f:
        json.dump(feed, f, indent=2)
        f.write("\n")
    print(f"Generated {output_path} with {len(feed['apps'])} apps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
