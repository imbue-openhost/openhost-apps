#!/usr/bin/env python3
"""Generate catalog.json from app TOML files.

Reads catalog.toml for metadata and apps/*/app.toml for app entries,
then writes catalog.json in the openhost.catalog.v1 feed format.

Usage:
    generate.py           # Write catalog.json
    generate.py --check   # Exit non-zero if catalog.json is stale; don't write
"""

import argparse
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

        feed_app = {
            "title": app.get("title", entry),
            "description": app.get("description", ""),
            "repo_url": app.get("repo_url", ""),
            "repo_ref": app.get("repo_ref", ""),
            "icon_url": app.get("icon_url", ""),
            "tags": app.get("tags", []),
            "categories": app.get("categories", []),
            "website_url": app.get("website_url", ""),
            "docs_url": app.get("docs_url", ""),
        }

        # Skip entries without a repo URL
        if not feed_app["repo_url"]:
            print(f"  skip {entry}: no repo_url", file=sys.stderr)
            continue

        apps.append(feed_app)

    # Within a single source, the catalog derives app IDs from the repo URL,
    # so duplicate repo URLs would collide. Fail the build so the feed
    # publisher has to fix it before the feed goes live.
    seen_repos: dict[str, int] = {}
    for i, app in enumerate(apps):
        repo = app["repo_url"]
        if repo in seen_repos:
            first = apps[seen_repos[repo]]["title"]
            print(
                f"error: duplicate repo_url {repo!r} (first seen in {first!r}); "
                "each app in a source must have a unique repo_url",
                file=sys.stderr,
            )
            sys.exit(1)
        seen_repos[repo] = i

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
