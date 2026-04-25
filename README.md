# openhost-apps

The official OpenHost app catalog feed. Consumed by [`openhost-catalog`](https://github.com/imbue-openhost/openhost-catalog) to populate its app listing.

This repo is data-only. The Go/Python code that reads this feed lives elsewhere.

## Structure

```
catalog.toml          # Catalog-level metadata (source name)
catalog.json          # Generated feed (what consumers fetch)
generate.py           # Builds catalog.json from the TOML sources
apps/<name>/app.toml  # One directory per app
```

## Feed format

The feed follows the `openhost.catalog.v1` schema. Each app entry has:

| Field          | Required | Description |
|----------------|----------|-------------|
| `name`                       | yes | The name the app deploys as. Must be lowercase alphanumeric with optional interior hyphens. Drop any `openhost-` prefix. |
| `title`                      | yes | Display name |
| `description`                | yes | One-line summary |
| `repo_url`                   | yes | GitHub repo containing the app's `openhost.toml` manifest |
| `repo_ref`                   | no  | Pin to a branch, tag, or commit (default: repo's default branch) |
| `icon_url`                   | no  | URL to an icon image |
| `tags`                       | no  | Array of search tags |
| `categories`                 | no  | Array of categories |
| `website_url`                | no  | Upstream project homepage |
| `docs_url`                   | no  | Documentation link |
| `openhost_integration_score` | no  | Integer 1-5 reflecting integration polish; omit if unrated. |
| `ai_generated`               | no  | Boolean, default `false`. Self-reported flag indicating that the **packaging** of the app (Dockerfile, manifests, glue scripts in the linked repo) was primarily authored with AI assistance. Does **not** describe the upstream application's contents. See "AI-generated packaging" below. |

### AI-generated packaging

When set to `true`, `ai_generated` tells catalog consumers (and ultimately the user installing the app) that the *packaging* code in `repo_url` was primarily produced with AI assistance, with limited or no human review of the resulting Dockerfile / manifest / scripts. This is a separate axis from `openhost_integration_score`, which is about quality and polish.

The flag is self-reported by the maintainer of the entry. Use it candidly: the goal is honest disclosure to the catalog user, not a precise audit. Set it to `true` if you would not be willing to claim "I read and understood every line of this packaging." Set it to `false` if the packaging is essentially a human-authored translation of upstream guidance, regardless of whether AI was used as an editor.

The flag describes only the packaging in the linked repo, not the upstream app. Immich packaged with AI assistance is `ai_generated = true`; the Immich source code itself is unrelated.

The `name` field is the app's identifier in the catalog: it is used in catalog URLs, pre-filled as the default deployed app name when installing, and must be unique within a source.

## Uniqueness

- **Within a source**: every app must have a unique `name` and a unique `repo_url`. Duplicates cause `generate.py` to fail.
- **Across sources**: the same name can appear in multiple source feeds without conflict. They show as separate entries in the catalog.

## Adding an app

1. Create `apps/<short-name>/app.toml` with the fields above.
2. Run `python3 generate.py` to regenerate `catalog.json`.
3. Commit both the new `app.toml` and the updated `catalog.json`.

## Development

### Regenerate the feed

```bash
python3 generate.py
```

### Check the feed is up to date (used by CI)

```bash
python3 generate.py --check
```

Exits non-zero if `catalog.json` is stale relative to the TOML sources.

### Pre-commit hook

Install [pre-commit](https://pre-commit.com/) and run:

```bash
pre-commit install
```

This installs a hook that runs `generate.py --check` before each commit and blocks stale `catalog.json` from being committed.

CI runs the same check on every PR.
