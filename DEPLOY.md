# Deploying CompliWise

CompliWise holds student IEP, ENL and MTSS records, which are covered by
FERPA. The production setup below serves everything over HTTPS, keeps the
database off the network and backs it up every night.

## What runs

`docker-compose.prod.yml` starts five containers on one server:

| Service    | Job                                                            | Reachable from        |
|------------|----------------------------------------------------------------|-----------------------|
| `caddy`    | HTTPS. Serves the app at `/` and the API at `/api`             | Ports 80 and 443      |
| `frontend` | The built React app (nginx)                                    | Caddy only            |
| `backend`  | FastAPI, one worker                                            | Caddy only            |
| `db`       | PostgreSQL 16                                                  | Backend and backup    |
| `backup`   | `pg_dump` every 24 hours into `./backups`                      | Nothing               |

The browser only ever talks to `https://<SITE_ADDRESS>`, so there is no
CORS, the session cookie is HTTPS-only, and the frontend never needs
rebuilding for a new server address.

## 1. Get a server

Any Linux machine with Docker and Docker Compose works: a machine on the
school network, or a small cloud VM (2 GB RAM is plenty for one school).

## 2. Pick how HTTPS works

- **School network only** (no public DNS name): set `CADDY_TLS=internal`.
  Caddy issues its own certificate. Each staff device has to trust Caddy's
  root certificate once, or browsers will show a warning. Copy it off the
  server with:

  ```bash
  docker compose -f docker-compose.prod.yml cp caddy:/data/caddy/pki/authorities/local/root.crt ./compliwise-root.crt
  ```

  and install it through your device management (Intune, Jamf, Google
  Admin, Group Policy).

- **Public DNS name** (e.g. `compliwise.myschool.org`): point the DNS
  record at the server, open ports 80 and 443, and set `CADDY_TLS` to an
  email address. Caddy gets and renews a Let's Encrypt certificate itself.

## 3. Configure

```bash
git clone <repository-url> && cd CompliWise
cp .env.example .env
```

Set at least:

```env
SESSION_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(48))">
POSTGRES_PASSWORD=<another long random value>
SITE_ADDRESS=compliwise.myschool.org     # or the server's IP
CADDY_TLS=internal                       # or you@myschool.org
```

The stack refuses to start if `SESSION_SECRET`, `POSTGRES_PASSWORD` or
`SITE_ADDRESS` is missing. `chmod 600 .env` so only the owner can read it.

## 4. Start it and finish setup straight away

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Then open `https://<SITE_ADDRESS>` **immediately** and complete the setup
wizard. Until the first admin exists, the setup page is open to anyone
who can reach the site, and whoever finishes it becomes the admin.

## 5. Backups

Dumps land in `./backups/compliwise-<date>.dump` and are kept for
`BACKUP_KEEP_DAYS` days (14 by default). They are on the same disk as the
database, so they will not survive losing the server. Copy them somewhere
else on a schedule, for example with `rclone` or `rsync` from cron.

Restore a dump into the running database:

```bash
docker compose -f docker-compose.prod.yml exec -T db \
  pg_restore --clean --if-exists -U compliwise -d compliwise < backups/compliwise-<date>.dump
```

Try a restore once before relying on the backups.

## Updating

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

The setup wizard only runs migrations on first install, so run
`alembic upgrade head` after every update that adds one.

## Things to know

- **Keep one backend worker.** Schedule generation runs in a background
  thread and its progress is kept in memory, so a second worker would not
  see it. A restart while a schedule is generating loses that job; start it
  again.
- **Logs:** `docker compose -f docker-compose.prod.yml logs -f backend`
  (or `caddy`, `backup`).
- **Local development** still uses `docker-compose.yml`, which serves over
  plain HTTP on ports 5173 and 8000. Don't use it for real student data.
