# WareWolf — cloud deployment

**Step-by-step Render guide:** see **`RENDER_DEPLOY_STEPS.md`** in this repo.

This project runs **Django + Gunicorn**, **PostgreSQL**, **Redis** (Celery), and **WhiteNoise** for static files. Email is optional and configured via environment variables.

## Environment variables

| Variable | Required (production) | Description |
|----------|----------------------|-------------|
| `DJANGO_SECRET_KEY` | Yes | Long random string; never commit. |
| `DJANGO_DEBUG` | Yes | Set to `False`. |
| `DJANGO_ALLOWED_HOSTS` | Yes | Comma-separated hostnames, e.g. `warewolf-web.onrender.com`. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Yes (HTTPS) | Comma-separated origins, e.g. `https://warewolf-web.onrender.com`. |
| `DATABASE_URL` | Yes | PostgreSQL URL (provided by Render/Railway when DB is linked). |
| `REDIS_URL` or `CELERY_BROKER_URL` | For Celery | Redis URL for task queue. |
| `DJANGO_DATABASE_SSL_REQUIRE` | Often | Set `true` if your provider requires SSL and the URL has no `sslmode`. |
| `EMAIL_*` | For real mail | Set `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD` (and usually `DEFAULT_FROM_EMAIL`) so Django sends via SMTP. If `DEBUG=True` and the password is empty, mail is printed to the **console** only. |

**Sending email to users:** copy `.env.example` to `.env`, add your Gmail (or other SMTP) credentials as described in `.env.example`, and restart `runserver`. On Render, add the same variables in the web service **Environment** (and on Celery worker services if tasks send mail).

Copy `.env.example` to `.env` for local development only.

## Deploy on Render (recommended for this repo)

1. Push this repository to GitHub/GitLab/Bitbucket.
2. In [Render](https://render.com), create a **PostgreSQL** instance and a **Redis** instance.
3. Create a **Web Service** from this repo:
   - **Build command:** `pip install -r requirements.txt && python manage.py collectstatic --noinput`
   - **Start command:** `gunicorn warewolf.wsgi:application --bind 0.0.0.0:$PORT`
   - **Pre-deploy / release command:** `python manage.py migrate --noinput`
4. Link the Postgres and Redis databases to the web service so `DATABASE_URL` and `REDIS_URL` are injected.
5. Set environment variables:
   - `DJANGO_DEBUG=False`
   - `DJANGO_SECRET_KEY` (generate a secure value)
   - `DJANGO_ALLOWED_HOSTS=<your-service-hostname>`
   - `DJANGO_CSRF_TRUSTED_ORIGINS=https://<your-service-hostname>`
   - Optionally `DJANGO_DATABASE_SSL_REQUIRE=true` if connections fail without SSL.
6. Redeploy. Open the site URL; create an admin user with `python manage.py createsuperuser` via Render **Shell** if needed.

You can also use the included `render.yaml` Blueprint: **New → Blueprint** and point it at this repo.

### Celery worker and beat (background jobs)

The web process alone does **not** run Celery workers. For scheduled tasks (anomaly scan, recommendations, digests), add two **Background Worker** services on Render with the **same** environment variables as the web service (especially `DATABASE_URL`, `REDIS_URL`, `DJANGO_SECRET_KEY`):

- **Worker:** `celery -A warewolf worker -l info`
- **Beat:** `celery -A warewolf beat -l info`

Use the same build command as the web service (`pip install -r requirements.txt`). Free tiers may limit concurrent workers; adjust plans if tasks do not run.

### Media uploads

Uploaded images are stored on disk (`MEDIA_ROOT`). On platforms with ephemeral disks, files can be lost on restart. For production durability, use object storage (e.g. S3) later; for demos, periodic backups or small uploads are usually acceptable.

## Docker

Build and run (supply env vars / `DATABASE_URL` yourself):

```bash
docker build -t warewolf .
docker run -e DATABASE_URL=... -e DJANGO_SECRET_KEY=... -e DJANGO_DEBUG=False -p 8000:8000 warewolf
```

## Local production-style check

```bash
pip install -r requirements.txt
set DJANGO_DEBUG=False
set DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
python manage.py collectstatic --noinput
python manage.py migrate
gunicorn warewolf.wsgi:application --bind 127.0.0.1:8000
```
