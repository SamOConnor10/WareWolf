# Deploy WareWolf on Render (step-by-step)

Do this **once**. You need a **GitHub** account and a **Render** account (free tier is fine for a demo).

> I cannot log into Render or GitHub for you — follow these steps in your browser.

---

## 1. Push the code to GitHub

1. Commit your project (without `.env` — it stays private on your PC).
2. Create a **new repository** on GitHub (e.g. `WareWolf`).
3. Push your local branch:

```bash
git remote add origin https://github.com/YOUR_USERNAME/WareWolf.git
git branch -M main
git push -u origin main
```

If the repo already exists, use `git push`.

---

## 2. Create the database and Redis on Render

1. Go to [dashboard.render.com](https://dashboard.render.com) and sign in.
2. **New +** → **PostgreSQL**
   - Name: e.g. `warewolf-db`
   - Region: **Frankfurt** (or same region you will use for the web service)
   - Plan: **Free** (or paid for production)
   - Create database
3. **New +** → **Key Value** (Redis-compatible; the dashboard may not show a separate “Redis” menu item)
   - Name: e.g. `warewolf-redis`
   - Same region as above
   - Create instance

Leave these open; you will **link** them to the web app in step 4.

---

## 3. Create the web service

1. **New +** → **Web Service**
2. Connect your **GitHub** account and select the **WareWolf** repository.
3. Configure:
   - **Name:** e.g. `warewolf` (your URL will be `https://warewolf.onrender.com`)
   - **Region:** same as Postgres/Redis (e.g. Frankfurt)
   - **Branch:** `main`
   - **Runtime:** Python 3
   - **Build command:**  
     `pip install -r requirements.txt && python manage.py collectstatic --noinput`
   - **Start command:**  
     `gunicorn warewolf.wsgi:application --bind 0.0.0.0:$PORT`
4. **Advanced** → **Pre-deploy / Deploy hook** (or **Release Command** depending on UI):  
   `python manage.py migrate --noinput`

---

## 4. Link Postgres and Redis

On the **web service** page:

1. **Environment** → **Add environment variable** → **Link database** → select your **PostgreSQL**.  
   Render injects `DATABASE_URL` automatically.
2. **Link** your **Redis** instance.  
   Render injects `REDIS_URL` (our `settings.py` reads it).

---

## 5. Set Django environment variables

Still under **Environment** for the web service, add:

| Key | Value |
|-----|--------|
| `DJANGO_DEBUG` | `False` |
| `DJANGO_SECRET_KEY` | A long random string (e.g. 50+ chars). Generate locally: `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_ALLOWED_HOSTS` | Your Render hostname only, **no** `https://` — e.g. `warewolf.onrender.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://warewolf.onrender.com` (use **your** exact URL) |
| `DJANGO_DATABASE_SSL_REQUIRE` | `true` |

**Email (optional):** same variables as in `.env.example` (`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`, etc.).

Save. Render will **redeploy**.

---

## 6. First visit, roles, and admin user

1. Open `https://YOUR-SERVICE.onrender.com`.
2. If you see a **500** error, check **Logs** on Render for the traceback.

### Running `migrate` / `setup_roles` / `createsuperuser` without Render Shell

On **many free or low-tier web services**, **Shell is unavailable or locked**. That is normal. You can run Django management commands **from your own PC** against the **same** Postgres database Render uses:

1. In the Render dashboard, open your **PostgreSQL** instance → **Connect** (or **Info**).
2. Copy the **External Database URL** (starts with `postgresql://`). It includes SSL settings Render expects.
3. On your machine, in the project folder, with your virtualenv active and dependencies installed (`pip install -r requirements.txt`):

**PowerShell (Windows):**

```powershell
$env:DATABASE_URL = "paste-external-database-url-here"
$env:DJANGO_DATABASE_SSL_REQUIRE = "true"
python manage.py migrate --noinput
python manage.py setup_roles
python manage.py createsuperuser
Remove-Item Env:DATABASE_URL
Remove-Item Env:DJANGO_DATABASE_SSL_REQUIRE
```

**bash:**

```bash
export DATABASE_URL="paste-external-database-url-here"
export DJANGO_DATABASE_SSL_REQUIRE=true
python manage.py migrate --noinput
python manage.py setup_roles
python manage.py createsuperuser
unset DATABASE_URL DJANGO_DATABASE_SSL_REQUIRE
```

Use a **strong** `DJANGO_SECRET_KEY` on Render for the live site; for one-off local commands against production, Django will still load settings (the app’s default insecure key only affects signing sessions you are not creating here).

`setup_roles` creates the **Admin / Manager / Staff** groups and permissions. **Staff** signup uses the `Staff` group; **Manager** signup creates a pending request and does **not** require that group—so if you only ever sign up as Manager, you still need a **superuser** (from `createsuperuser` above) to approve Manager requests in the admin UI.

If your Render plan **does** include Shell on the web service, you may run the same three commands there instead.

4. Try **Sign up** again, or log in with the superuser you created.

---

## Copying your development database to Render (same data as local)

Render cannot connect to a database on your laptop. The hosted Postgres is a **separate** server. To get the **same populated data** as dev, you **export** from dev and **import** into Render (this **replaces** whatever is already in the Render database).

**Before you start:** back up Render if it has anything you care about. Syncing from dev will overwrite production data.

### A. Django `dumpdata` / `loaddata` (works well for this project)

On your PC, with the **same** settings you use for development (no `DATABASE_URL`, or your local Postgres in `.env`):

```bash
python manage.py dumpdata --natural-foreign --natural-primary --indent 2 --exclude contenttypes --exclude auth.permission --exclude sessions --exclude admin.logentry -o warewolf_backup.json
```

Then load into **Render’s** database (use the **External Database URL** from the Postgres dashboard):

**PowerShell:**

```powershell
$env:DATABASE_URL = "paste-render-external-database-url"
$env:DJANGO_DATABASE_SSL_REQUIRE = "true"
python manage.py migrate --noinput
python manage.py flush --noinput
python manage.py loaddata warewolf_backup.json
python manage.py setup_roles
Remove-Item Env:DATABASE_URL, Env:DJANGO_DATABASE_SSL_REQUIRE
```

`flush` deletes existing rows so `loaddata` does not hit duplicate primary keys. `setup_roles` recreates **Admin / Manager / Staff** groups and ties permissions to them after a flush.

If `loaddata` fails (often due to `exclude` choices), run `dumpdata` without excludes or export only the apps you need, and adjust excludes per the error message.

**Uploaded files (images):** database rows only reference paths under `media/`. Copy your local `media/` folder contents to wherever Render stores uploads if you use persistent storage; the free web disk is often **ephemeral**, so treat production uploads as needing object storage (e.g. S3) for anything you must keep.

### B. `pg_dump` / `pg_restore` (only if both sides are PostgreSQL)

If your dev DB is Postgres (this project’s default without `DATABASE_URL` is local Postgres), you can use PostgreSQL tools to clone the whole database in one step. You need `pg_dump`/`pg_restore` installed (e.g. [PostgreSQL client](https://www.postgresql.org/download/) on Windows). Point the restore target at Render’s **external** connection string. Apply **migrations on dev first** so schema matches the app you deploy; mismatched versions can break restores.

---

## 7. Celery (background tasks) — optional on free tier

The **web** process does **not** run Celery. For anomaly scans and scheduled emails, add **two** Background Workers (same repo, same env as web):

- **Worker:** `celery -A warewolf worker -l info`
- **Beat:** `celery -A warewolf beat -l info`

Link the same **Postgres** and **Redis** and copy `DJANGO_SECRET_KEY` and other vars. Free tier may limit workers; the site will still work without them, but scheduled jobs will not run.

---

## Troubleshooting

| Problem | What to try |
|--------|------------|
| Build timeout / memory | Prophet is heavy; upgrade instance or use a paid plan. |
| `DisallowedHost` | `DJANGO_ALLOWED_HOSTS` must match the hostname **exactly** (no port, no `https`). |
| CSRF / login fails | Set `DJANGO_CSRF_TRUSTED_ORIGINS` to `https://your-host.onrender.com`. |
| Database connection | Ensure Postgres is linked; `DATABASE_URL` is set; try `DJANGO_DATABASE_SSL_REQUIRE=true`. |
| Free tier sleeps | First request after idle can take ~30–60s. |
| No Shell / Shell locked | Use **External Database URL** from Postgres and run `manage.py` on your PC (see §6). |
| **403** on Stock / Orders / Locations (dashboard works) | Those pages need Django permissions from **Staff**, **Manager**, or **Admin** groups. Run `python manage.py setup_roles` against production, then in **Admin → Users** assign the right **group** (or use **Approve** on the manager request). Active users with no group get 403. |

---

## Using the Blueprint (`render.yaml`)

You can use **New → Blueprint** and point at this repo. You must still **create** Postgres and Redis in the dashboard and **link** them, and set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, and `DJANGO_CSRF_TRUSTED_ORIGINS` manually (Render cannot guess your hostname before first deploy).
