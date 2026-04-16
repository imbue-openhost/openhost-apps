#!/usr/bin/env python3
"""Generate catalog.json from app TOML files.

Reads catalog.toml for metadata and apps/*/app.toml for app entries,
then writes catalog.json in the openhost.catalog.v1 feed format.
"""

import json
import os
import sys
from datetime import datetime, timezone

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


def main():
    root = os.path.dirname(os.path.abspath(__file__))

    # Load catalog metadata
    catalog_path = os.path.join(root, "catalog.toml")
    catalog = load_toml(catalog_path).get("catalog", {})

    source_id = catalog.get("source_id", "official")
    source_name = catalog.get("name", "OpenHost Official")

    # Load all app entries
    apps_dir = os.path.join(root, "apps")
    apps = []

    for entry in sorted(os.listdir(apps_dir)):
        app_toml = os.path.join(apps_dir, entry, "app.toml")
        if not os.path.isfile(app_toml):
            continue

        data = load_toml(app_toml)
        app = data.get("app", {})
        store = data.get("store", {})

        # Merge store fields into app-level fields
        feed_app = {
            "title": app.get("title", app.get("name", entry)),
            "description": app.get("description", ""),
            "repo_url": app.get("repo_url", ""),
            "repo_ref": app.get("repo_ref", ""),
            "default_app_name": app.get("default_app_name", entry),
            "icon_url": app.get("icon_url", store.get("icon_url", "")),
            "tags": app.get("tags", store.get("tags", [])),
            "categories": app.get("categories", store.get("categories", [])),
            "website_url": app.get("website_url", app.get("homepage", "")),
            "docs_url": app.get("docs_url", ""),
            "minimum_openhost_version": app.get(
                "minimum_openhost_version", store.get("min_openhost_version", "")
            ),
        }

        # Skip entries without a repo URL
        if not feed_app["repo_url"]:
            print(f"  skip {entry}: no repo_url", file=sys.stderr)
            continue

        apps.append(feed_app)

    feed = {
        "schema": "openhost.catalog.v1",
        "source_id": source_id,
        "source_name": source_name,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "apps": apps,
    }

    output_path = os.path.join(root, "catalog.json")
    with open(output_path, "w") as f:
        json.dump(feed, f, indent=2)
        f.write("\n")

    print(f"Generated {output_path} with {len(apps)} apps")


if __name__ == "__main__":
    main()
