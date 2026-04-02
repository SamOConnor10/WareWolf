# How to make WareWolf send real emails (simple steps)

WareWolf reads email settings from a file named **`.env`** in the same folder as `manage.py`.  
That file is **not** uploaded to GitHub (it is private on your machine).

## Step 1 — Open the `.env` file

1. In Cursor: click **`.env`** in the left file list (project root).  
   If you do not see it, press `Ctrl+P`, type `.env`, press Enter.

2. You will see three lines to edit:
   - `EMAIL_HOST_USER=...`
   - `EMAIL_HOST_PASSWORD=...`
   - `DEFAULT_FROM_EMAIL=...`

## Step 2 — Put your Gmail address in

Replace `PUT_YOUR_GMAIL_HERE` with your real Gmail address (no spaces).

Example:

```text
EMAIL_HOST_USER=samarthuroconnor@gmail.com
DEFAULT_FROM_EMAIL=WareWolf <samarthuroconnor@gmail.com>
```

## Step 3 — Get a Gmail “App password” (not your normal login password)

Google does not let you use your normal Gmail password for apps. You must use a **16-character app password**.

1. Open a browser and go to: **https://myaccount.google.com/security**
2. Turn on **2-Step Verification** if it is not on (Google requires this for app passwords).
3. Search the page for **App passwords** (or go to: **https://myaccount.google.com/apppasswords**).
4. Create a new app password:
   - App: **Mail**
   - Device: **Other** → type `WareWolf`
5. Google shows **16 characters** (sometimes like `abcd efgh ijkl mnop`). Copy the whole thing.

## Step 4 — Paste the app password into `.env`

Set:

```text
EMAIL_HOST_PASSWORD=abcdefghijklmnop
```

Use the 16 letters with **no spaces**, or **with spaces** — both usually work.

Save the file (`Ctrl+S`).

## Step 5 — Restart the Django server

Stop the server (`Ctrl+C` in the terminal), then start again:

```text
python manage.py runserver
```

After this, when the app sends emails (alerts, digests, etc.), they should go through Gmail to real addresses.

## If something fails

- **“Authentication failed”**: Wrong app password, or 2-Step Verification not enabled.
- **Still no email**: Check spam folder. For testing, send to the same Gmail you use.
- **Production (Render)**: Add the same `EMAIL_*` variables in the Render dashboard **Environment** tab (do not paste passwords in Git).
