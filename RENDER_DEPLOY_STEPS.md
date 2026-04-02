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
3. **New +** → **Redis**
   - Name: e.g. `warewolf-redis`
   - Same region as above
   - Create Redis

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

## 6. First visit and admin user

1. Open `https://YOUR-SERVICE.onrender.com`.
2. If you see a **500** error, check **Logs** on Render for the traceback.
3. Create a superuser: **Shell** on the web service (Render dashboard):

```bash
python manage.py createsuperuser
```

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

---

## Using the Blueprint (`render.yaml`)

You can use **New → Blueprint** and point at this repo. You must still **create** Postgres and Redis in the dashboard and **link** them, and set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, and `DJANGO_CSRF_TRUSTED_ORIGINS` manually (Render cannot guess your hostname before first deploy).
