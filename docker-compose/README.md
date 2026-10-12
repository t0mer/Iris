# Docker Compose examples

Ready-to-run Compose files for Iris with each database, and one for OpenWA, the WhatsApp gateway Iris reads from.

| File | What it runs |
|---|---|
| [`sqlite.yml`](sqlite.yml) | Iris with its built-in SQLite database. One container, the simplest setup. |
| [`mysql.yml`](mysql.yml) | Iris and MySQL 8.4 (utf8mb4), started in the right order. |
| [`postgres.yml`](postgres.yml) | Iris and PostgreSQL 16, started in the right order. |
| [`openwa.yml`](openwa.yml) | OpenWA on its own, with its container locked down. |

Pick **one** Iris file (the three Iris files are alternatives, not parts of one stack) and add `openwa.yml` if you do not have an OpenWA yet.

## Set up

```bash
cd docker-compose
cp .env.example .env
openssl rand -base64 32     # paste into IRIS_SECRET_KEY in .env, and back it up
$EDITOR .env                # admin password, public URL, database password
docker compose -f sqlite.yml up -d      # or mysql.yml / postgres.yml
docker compose -f openwa.yml up -d      # if you need OpenWA
```

Compose refuses to start and says which value is missing if a required one is empty. Open Iris at `http://localhost:8080` and sign in with the admin account from `.env`.

| Variable | Used by | Purpose |
|---|---|---|
| `IRIS_SECRET_KEY` | Iris | Encrypts every stored secret. Keep a backup: without it you must re-enter them. |
| `IRIS_ADMIN_USERNAME`, `IRIS_ADMIN_PASSWORD` | Iris | First-run admin account (the password is ignored afterwards). |
| `IRIS_PUBLIC_BASE_URL` | Iris | The address OpenWA reaches Iris on. It builds the webhook URLs and alert links. |
| `IRIS_METRICS_TOKEN` | Iris | Makes `/metrics` require `Authorization: Bearer <token>`. Set it if the Iris port is reachable from outside. |
| `IRIS_PORT`, `IRIS_IMAGE` | Iris | Published port (default 8080) and required reviewed image tag or digest. |
| `DB_PASSWORD` | MySQL, PostgreSQL | The database password. Use letters and digits only: it goes into a connection URL as is. |
| `OPENWA_IMAGE` | OpenWA | Required tested immutable image digest. Automatic Watchtower updates are disabled. |
| `OPENWA_PORT`, `TZ` | OpenWA | Port on localhost (default 2785) and time zone for its logs. |

## Which database?

- **SQLite** needs nothing else and is fine for a family. Search matches the start of words.
- **MySQL** and **PostgreSQL** keep the messages in a database server you can back up and inspect on its own. Search matches any part of a word. The database is created empty and Iris creates its tables at start.
- With `mysql.yml` or `postgres.yml` the database is set by `IRIS_DATABASE_URL`, so **Settings > Database** only shows what is in use. To move existing SQLite data, start from `sqlite.yml`, use **Copy my data** in Settings > Database, then switch files. See [Choosing a database](../README.md#choosing-a-database).
- Only one Iris container may use a database.

## Connecting OpenWA to Iris

1. Start OpenWA and open `http://localhost:2785`. The first start creates an admin API key: `docker exec openwa cat /app/data/.api-key`.
2. Create one session per child's phone and scan its QR code with WhatsApp on that phone.
3. In Iris, open **Phones > Add a phone**: enter the child's name, OpenWA's address, the session's full ID (not its name) and the API key. Iris shows the phone's private webhook address.
4. Press **Register in OpenWA** (or paste the address into the session's webhooks yourself).

**OpenWA refuses to send webhooks to private network addresses** (`Destination address is not allowed`). `IRIS_PUBLIC_BASE_URL` must therefore be a public hostname (a reverse proxy or a tunnel such as Cloudflare Tunnel) that reaches Iris, not `http://192.168.x.x:8080`. Expose only `/webhooks/*` publicly if you can.

## Good to know

- The Iris port is published on all interfaces so OpenWA and your phone can reach it. `/metrics` is open unless you set `IRIS_METRICS_TOKEN`, so set it, or bind the port to localhost (`127.0.0.1:8080:8080`) and publish only `/webhooks/*` through your proxy.
- The MySQL root password is random and unused; Iris has its own limited user.
- `openwa.yml` publishes OpenWA on `127.0.0.1` only and runs it read-only with all capabilities dropped except those its entrypoint needs. Put a TLS reverse proxy in front to reach it from other machines, and remove `CSP_UPGRADE_INSECURE_REQUESTS` once you do (it is there so the dashboard works over plain HTTP).
- OpenWA's `openwa-data` volume holds your WhatsApp logins. Back it up like a secret.
- Pin versions for repeatable installs: set `IRIS_IMAGE=techblog/iris:<version>` or an immutable digest, and set the required `OPENWA_IMAGE` to your tested gateway digest.
- Update with `docker compose -f <file> pull && docker compose -f <file> up -d`. Data lives in named volumes and survives.
- Stop everything and **keep** the data: `docker compose -f <file> down`. Add `-v` only if you want the data deleted.
