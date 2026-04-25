#!/usr/bin/env python3
"""Generate catalog.json from app TOML files.

Reads catalog.toml for metadata and apps/*/app.toml for each app
entry. Emits catalog.json in the openhost.catalog.v1 feed format.

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


def validate_score(app_toml_path: str, value) -> int:
    """Validate an openhost_integration_score value.

    Apps may omit the field; an omitted score is emitted as 0 in
    catalog.json, which downstream UIs render as "unrated". When
    the field is present, it must be an int in 1-5.
    """
    if value is None:
        return 0
    if not isinstance(value, int) or value < 1 or value > 5:
        print(
            f"error: {app_toml_path}: openhost_integration_score must be an integer 1-5, got {value!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


def validate_ai_generated_flag(app_toml_path: str, field_name: str, value) -> bool:
    """Validate one of the AI-generated provenance flags.

    Apps may omit the field; treated as false. When present it must
    be a literal boolean (not 0/1 or a string).
    """
    if value is None:
        return False
    if not isinstance(value, bool):
        print(
            f"error: {app_toml_path}: {field_name} must be a boolean, got {value!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


def build_feed(root: str) -> dict:
    """Build the feed dict (excluding generated_at) from the source TOML files."""
    catalog_path = os.path.join(root, "catalog.toml")
    catalog = load_toml(catalog_path).get("catalog", {})

    source_id = catalog.get("source_id", "official")
    source_name = catalog.get("name", "OpenHost Official")

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

        score = validate_score(app_toml, app.get("openhost_integration_score"))
        # Two independent self-reported provenance flags. The packaging
        # flag describes the Dockerfile / manifests / glue code in the
        # linked repo; the application flag describes the upstream
        # application's own source code. They are intentionally
        # separate because an AI may have written one but not the
        # other (e.g. AI-packaged a human-written app).
        ai_generated_packaging = validate_ai_generated_flag(
            app_toml, "ai_generated_packaging", app.get("ai_generated_packaging")
        )
        ai_generated_application = validate_ai_generated_flag(
            app_toml, "ai_generated_application", app.get("ai_generated_application")
        )

        # Reject the legacy single `ai_generated` field outright so
        # nobody silently keeps the old semantics. Authors must opt
        # into the new split explicitly.
        if "ai_generated" in app:
            print(
                f"error: {app_toml}: legacy `ai_generated` field is no longer "
                "supported; use `ai_generated_packaging` and "
                "`ai_generated_application` instead",
                file=sys.stderr,
            )
            sys.exit(1)

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
            "openhost_integration_score": score,
            "ai_generated_packaging": ai_generated_packaging,
            "ai_generated_application": ai_generated_application,
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

    return {
        "schema": "openhost.catalog.v1",
        "source_id": source_id,
        "source_name": source_name,
        "apps": apps,
    }


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
