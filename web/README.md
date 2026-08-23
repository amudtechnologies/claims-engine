# web

The public-facing Django site — `home` (company page, document-number search
hero — NIT or cédula) and
`judicial_deposits` (radar landing page, search logic). See `CLAUDE.md` at
the repo root for the app split and why `results` lives in `home`.

## Local development

```bash
uv sync
cd web
uv run python manage.py migrate
uv run python manage.py sync_core_cache   # needs AWS creds; populates the document-number search cache
uv run python manage.py runserver
```

With no env vars set, this runs exactly like before: `DEBUG=True`, sqlite at
`web/db.sqlite3`, the built-in insecure `SECRET_KEY`, no `ALLOWED_HOSTS`
restriction.

## Environment variables

| Variable | Used for | Default |
|---|---|---|
| `DJANGO_SECRET_KEY` | Django's `SECRET_KEY` | dev placeholder — **must** be set in production |
| `DJANGO_DEBUG` | `DEBUG` (`'True'`/`'False'`) | `True` |
| `DJANGO_ALLOWED_HOSTS` | `ALLOWED_HOSTS`, comma-separated | empty |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `CSRF_TRUSTED_ORIGINS`, comma-separated, scheme included (e.g. `https://amud.co`) | empty |
| `DB_HOST` | Switches `DATABASES` to Postgres when set; sqlite otherwise | unset (sqlite) |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Postgres connection, required when `DB_HOST` is set | — |
| `DB_PORT` | Postgres port | `5432` |
| `CLAIMS_ENGINE_BUCKET` | S3 bucket `sync_core_cache` reads from | `amud-technologies` |
| `CORE_CACHE_SYNC_INTERVAL_SECONDS` | Background re-sync interval in the container entrypoint | `3600` |
| `GUNICORN_WORKERS` | Gunicorn worker count | `2` |
| `PORT` | Port gunicorn binds | `8000` |

AWS credentials for `sync_core_cache`'s `boto3` calls come from the
container's IAM role in production (App Runner instance role / ECS task
role) — never static access keys there. Static keys stay confined to the
pipeline's GitHub Actions secrets (D25); the web app is a different trust
boundary.

## Container

Built from the **repo root**, not `web/` — the app imports `src/claims_engine`
(`judicial_deposits/core_cache.py`), so both trees have to be in the build
context:

```bash
docker build -t claims-engine-web -f Dockerfile .
docker run --rm -p 8000:8000 \
  -e DJANGO_DEBUG=False \
  -e DJANGO_ALLOWED_HOSTS=localhost \
  -e AWS_ACCESS_KEY_ID=... -e AWS_SECRET_ACCESS_KEY=...  # local run only; use an IAM role in AWS \
  claims-engine-web
```

The entrypoint (`web/entrypoint.sh`) runs migrations, does a blocking first
`sync_core_cache` so the app never serves "not synced" on a cold start, then
re-syncs in the background on `CORE_CACHE_SYNC_INTERVAL_SECONDS` alongside
gunicorn — `core_cache.py` is explicit that this has to stay off the
request path.

## Deploying to AWS

Recommended target: **App Runner**, built from this `Dockerfile`. It builds
straight from the image, handles TLS/scaling/health checks, and needs no
servers to patch — a better fit for this project's stated bias against
heavier infra (`CLAUDE.md`'s excluded-stack list) than standing up ECS or a
raw EC2 box.

1. **RDS Postgres** (small instance, e.g. `db.t4g.micro`) for Django's own
   auth/session/admin tables — this is the "system's own transactional
   tables" half of the serving layer per `CLAUDE.md`, unrelated to the
   `marts` layer, which doesn't exist yet (Phase 6 is deferred). Set
   `DB_HOST`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`.
2. **IAM role** for the App Runner instance with read access to
   `s3://amud-technologies/core/*` (and `raw/`/`staging/`/`marts/` only if
   the app ever needs them — it doesn't today) — this is what
   `sync_core_cache` authenticates with, no access keys in the environment.
3. **App Runner service** from this Dockerfile (source: ECR, or GitHub with
   auto-build). Set the env vars above; `PORT` doesn't need to be set — App
   Runner defaults to 8000, matching the entrypoint's default.
4. **Custom domain + `DJANGO_ALLOWED_HOSTS`/`DJANGO_CSRF_TRUSTED_ORIGINS`**
   once the domain is attached.

`sync_core_cache` runs per-instance, not shared — if App Runner scales to
multiple instances each keeps its own cache in sync independently. That's
redundant S3 traffic, not a correctness problem, and matches this project's
preference for no shared-state orchestration.
