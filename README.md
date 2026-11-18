# Link Registry

A small, public, read-only index of URLs served at **https://urls.yashwanthgowdam.in**.
Anyone can view the list. Adding, editing and deleting requires a password **and** a TOTP code
from an authenticator app.

- App: Flask + gunicorn, SQLite (WAL) on a Docker named volume
- TLS / reverse proxy: Caddy (automatic Let's Encrypt certificates)
- CI/CD: GitHub Actions. Tests run on GitHub's runners; deployment runs on a self-hosted runner
  installed on the target VM, so no SSH access is exposed to GitHub.

```
Browser --443--> Caddy --(internal docker network)--> gunicorn/Flask --> /data/urls.db (volume)
                                                         ^
GitHub push -> test job (GitHub) -> deploy job (runner on the VM) -> docker compose up
```

Contents: [1 Prerequisites](#1-prerequisites) · [2 DNS](#2-dns) · [3 Prepare the VM](#3-prepare-the-vm) ·
[4 GitHub repository](#4-github-repository) · [5 Self-hosted runner](#5-self-hosted-runner-on-the-vm) ·
[6 Runtime secrets](#6-runtime-secrets-on-the-vm) · [7 First deploy](#7-first-deploy) ·
[8 Create your admin user](#8-create-your-admin-user-with-mfa) · [9 Verify](#9-verify-the-installation) ·
[10 Daily operations](#10-daily-operations) · [11 Backup and restore](#11-backup-and-restore) ·
[12 Troubleshooting](#12-troubleshooting) · [13 Local development](#13-local-development) ·
[14 Security design](#14-security-design)

---

## 1. Prerequisites

| Item | Requirement |
|---|---|
| VM | Ubuntu 22.04 or 24.04 LTS, 1 vCPU, 1 GB RAM, 10 GB disk, public IPv4 |
| Access | A sudo-capable user on the VM and the VM's public IP |
| Domain | Control over DNS for `yashwanthgowdam.in` |
| GitHub | An account and permission to create a repository |
| Phone | An authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, Aegis, ...) |

Commands below assume Ubuntu. Replace `deploy` with whatever Linux user you prefer to run the runner.

## 2. DNS

Create an `A` record at your DNS provider:

| Type | Name | Value | TTL |
|---|---|---|---|
| A | `urls` | `<VM public IP>` | 300 |

If the VM has IPv6, also add an `AAAA` record. Do not add one if IPv6 is not reachable on the VM,
or certificate issuance will fail.

Check propagation from your laptop (it must print the VM's IP before you continue):

```bash
dig +short urls.yashwanthgowdam.in
```

## 3. Prepare the VM

SSH in as an admin user, then:

### 3.1 Update and install tools

```bash
sudo apt-get update && sudo apt-get -y upgrade
sudo apt-get -y install ca-certificates curl rsync git ufw
```

### 3.2 Create a deploy user (the runner will run as this user)

```bash
sudo adduser --disabled-password --gecos "" deploy
```

### 3.3 Install Docker Engine and the compose plugin

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
docker --version && docker compose version
```

Membership of the `docker` group is effectively root on this VM. That is why the runner must only
ever execute workflows from your own private repository (see section 4.4).

### 3.4 Firewall

Caddy needs 80 (certificate challenge and redirect) and 443 (HTTPS, plus UDP for HTTP/3). Keep SSH open.

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw enable
sudo ufw status verbose
```

If your cloud provider has its own security group or firewall, open the same ports there too.
Note: Docker publishes ports by editing iptables directly, so ufw does not block published
container ports on its own. This stack publishes only 80 and 443, so that is fine. Do not add
additional `ports:` entries to the compose file.

### 3.5 Create the application directory

```bash
sudo install -d -o deploy -g deploy -m 755 /opt/urls
```

## 4. GitHub repository

### 4.1 Create the repository

On GitHub: **New repository**, name it for example `urls-registry`, visibility **Private**,
and do not add a README or .gitignore (this project already has them).

### 4.2 Push the code

On your laptop, from the unzipped project folder:

```bash
git init -b main
git add .
git commit -m "Initial commit"
git remote add origin git@github.com:<your-user>/urls-registry.git
git push -u origin main
```

The first push will start the workflow. Its `test` job should pass. The `deploy` job will wait,
because no runner exists yet. That is expected.

### 4.3 Create the `production` environment

Repository **Settings → Environments → New environment** → name it exactly `production`.
Optional but recommended: tick **Required reviewers** and add yourself, so each deploy needs a click.

### 4.4 Protect `main` and lock down Actions

- **Settings → Branches → Add rule** for `main`: require a pull request and require the `test` status check.
- **Settings → Actions → General**: under *Fork pull request workflows* select
  *Require approval for all outside collaborators*. Keep the repository private so nobody else can
  trigger jobs on your VM.

## 5. Self-hosted runner on the VM

### 5.1 Get the registration commands

Repository **Settings → Actions → Runners → New self-hosted runner** → choose **Linux** and your
CPU architecture (`x64` or `arm64`). GitHub shows a *Download* block and a *Configure* block with a
short-lived token. Use those exact commands, because they always point to the current runner version.

### 5.2 Install and register it as the `deploy` user

```bash
sudo -iu deploy
mkdir -p ~/actions-runner && cd ~/actions-runner
# Paste the "Download" commands from GitHub here (curl ... && tar xzf ...)
```

Then configure, using the token GitHub displayed and these labels:

```bash
./config.sh --url https://github.com/<your-user>/urls-registry \
            --token <TOKEN_FROM_GITHUB> \
            --labels urls-prod \
            --unattended --name urls-vm
exit    # back to your admin user
```

The workflow targets `[self-hosted, linux, urls-prod]`. Self-hosted runners automatically carry
`self-hosted` and `linux`, and you added `urls-prod`.

### 5.3 Run it as a service so it survives reboots

```bash
cd /home/deploy/actions-runner
sudo ./svc.sh install deploy
sudo ./svc.sh start
sudo ./svc.sh status
```

In GitHub, **Settings → Actions → Runners** should now show `urls-vm` as **Idle**.

## 6. Runtime secrets on the VM

The session-signing key lives only on the VM, outside the git checkout, so deploys never overwrite it.

```bash
sudo -iu deploy
umask 077
printf 'SECRET_KEY=%s\nCOOKIE_SECURE=1\n' "$(openssl rand -hex 32)" > /opt/urls/.env
ls -l /opt/urls/.env        # expect: -rw------- deploy deploy
exit
```

Never commit this file. Changing `SECRET_KEY` later signs everyone out; it does not affect stored data.

## 7. First deploy

1. In GitHub open **Actions**, pick the latest run of `ci-cd` (or push any commit to `main`,
   or use **Re-run all jobs**).
2. `test` runs on GitHub: ruff, pytest, and a Docker build.
3. If you enabled required reviewers, approve the `production` deployment.
4. `deploy` runs on your VM: it syncs the code to `/opt/urls/app`, runs
   `docker compose up -d --build --wait`, reloads Caddy, then calls `/healthz` over HTTPS.

The first run takes a few minutes: the image is built and Caddy requests a certificate. On the VM:

```bash
cd /opt/urls/app
docker compose ps          # both services should be "running" and app "healthy"
docker compose logs caddy  # look for "certificate obtained successfully"
```

## 8. Create your admin user (with MFA)

On the VM, as `deploy`:

```bash
cd /opt/urls/app
docker compose exec app python -m app.cli create-user yashwanth
```

1. Type a password of at least 12 characters (twice). Use a password manager.
2. A QR code is printed in the terminal. Scan it with your authenticator app.
   If the QR does not render, enter the printed *manual entry key* instead.
3. Clear your terminal scrollback so the key does not linger.

Other commands:

```bash
docker compose exec app python -m app.cli list-users
docker compose exec app python -m app.cli create-user yashwanth --force   # reset password and MFA
docker compose exec app python -m app.cli delete-user someone
```

## 9. Verify the installation

From your laptop:

```bash
curl -sI https://urls.yashwanthgowdam.in/ | head -20        # 200 plus security headers
curl -s  https://urls.yashwanthgowdam.in/healthz            # ok
curl -sI http://urls.yashwanthgowdam.in/ | head -3          # 308 redirect to https
```

Then in a browser:

1. Open the site in a private window. You see the list with no login prompt and no Add or Delete controls.
2. Click **Sign in to edit**, enter username and password, then the 6-digit code.
3. Click **Add link**, create one, edit it, delete it.
4. Click **Sign out**.
5. Optional: confirm the data survives a redeploy by adding a link, re-running the workflow, and checking it is still there.

## 10. Daily operations

| Task | How |
|---|---|
| Add, edit, delete links | Sign in on the website. No deploy needed |
| Change the application | Edit code, open a PR, merge to `main`. CI deploys automatically |
| Roll back | Revert the bad commit on `main` and push; the pipeline redeploys the previous code |
| View application logs | `docker compose -f /opt/urls/app/docker-compose.yml logs -f app` |
| Audit trail | The app logs `link.create`, `link.update`, `link.delete`, `auth.login`, `auth.failure` with user and IP |
| Lost phone or password | `create-user <name> --force` on the VM (section 8) |
| Sign out everyone | Change `SECRET_KEY` in `/opt/urls/.env`, then `docker compose up -d` in `/opt/urls/app` |
| Patch dependencies | Dependabot opens weekly PRs; CI tests them before you merge |
| Restart | `docker compose -f /opt/urls/app/docker-compose.yml restart` |

Containers use `restart: unless-stopped`, so everything returns after a VM reboot.

## 11. Backup and restore

Data is stored in the Docker volume `urls_data` (file `/data/urls.db` inside the container).
Deploys and image rebuilds never delete it. Only `docker compose down -v` or `docker volume rm` would.

### 11.1 Nightly backup

```bash
sudo install -d -o deploy -g deploy -m 700 /var/backups/urls
sudo -iu deploy crontab -e
```

Add:

```
15 2 * * * /opt/urls/app/scripts/backup.sh >> /var/backups/urls/backup.log 2>&1
```

Run it once by hand to confirm: `/opt/urls/app/scripts/backup.sh`.
The script uses SQLite's online backup API (safe while the app is running) and keeps 14 copies.
Copy `/var/backups/urls` off the VM (object storage, another host) so a lost VM does not lose the data.
Treat backups as sensitive: they contain password hashes and MFA secrets.

### 11.2 Restore

```bash
cd /opt/urls/app
docker compose stop app
docker run --rm -v urls_data:/data -v /var/backups/urls:/b alpine sh -c \
  'rm -f /data/urls.db-wal /data/urls.db-shm && cp /b/urls-<STAMP>.db /data/urls.db && chown 10001:10001 /data/urls.db'
docker compose start app
```

## 12. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `deploy` job stays queued | Runner offline or labels wrong. `sudo ./svc.sh status` in the runner folder; labels must include `urls-prod` |
| `permission denied ... docker.sock` | `deploy` is not in the `docker` group, or the runner service started before you added it. `sudo usermod -aG docker deploy`, then `sudo ./svc.sh stop && sudo ./svc.sh start` |
| `Missing /opt/urls/.env` | Do section 6 |
| App exits with `SECRET_KEY must be set` | `.env` is empty or shorter than 32 characters. Regenerate it, then `docker compose up -d` |
| Browser shows a certificate error | DNS not pointing to the VM yet, or ports 80/443 blocked by ufw or the cloud firewall. Check `docker compose logs caddy`. Let's Encrypt rate-limits repeated failures, so fix DNS first |
| 502 Bad Gateway | The app container is unhealthy. `docker compose ps`, then `docker compose logs app` |
| Smoke test fails but site works | Runner VM cannot resolve the public name. Check `curl -v https://urls.yashwanthgowdam.in/healthz` on the VM |
| "Too many failed attempts" | 5 failed tries per user (20 per IP) lock sign-in for 15 minutes. Counters live in the database, so restarting does not clear them. Wait it out |
| Verification code always rejected | Phone clock is wrong (enable automatic time), or the code was already used. Wait for the next code. If the device is gone, use `create-user --force` |
| Can sign in locally over http but not on the site | Local dev needs `COOKIE_SECURE=0`; production must keep `1` and use https |
| Writes fail with "readonly database" | Volume ownership drifted. `docker compose exec -u root app chown -R 10001:10001 /data` (the root filesystem is read-only, but `/data` is writable) |

## 13. Local development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest && ruff check .

export DATA_DIR=./data COOKIE_SECURE=0 SECRET_KEY=$(openssl rand -hex 32)
python -m app.cli create-user dev
flask --app app run --debug
```

Open http://127.0.0.1:5000. Do not use `COOKIE_SECURE=0` in production.

## 14. Security design

| Concern | Control |
|---|---|
| Passwords | Argon2id. Unknown usernames take a comparable code path to avoid user enumeration |
| MFA | TOTP (RFC 6238) with ±1 step drift; each time step can be used once (atomic replay protection) |
| Brute force | 5 failures per user and 20 per IP per 15 minutes, stored in SQLite so all workers share it |
| Sessions | Signed cookie, `__Host-` prefix, Secure, HttpOnly, SameSite=Lax, 8-hour absolute lifetime, user re-checked in the DB every request, fresh session at login (no fixation), 5-minute window between password and code |
| CSRF | Per-session token on every state-changing POST, constant-time comparison |
| XSS | Jinja autoescaping, strict CSP (`script-src 'self'`, no inline JS or CSS), `rel="noopener noreferrer"` on outbound links |
| Dangerous URLs | Only `http` and `https`, no embedded credentials, no whitespace or control characters, length limits |
| SQL injection | Parameterised queries only |
| Transport | HTTPS via Caddy, HSTS, HTTP redirected to HTTPS |
| Container | Non-root user, read-only root filesystem, all capabilities dropped, `no-new-privileges`, app port not published |
| Secrets | `SECRET_KEY` only in `/opt/urls/.env` on the VM (mode 600), never in git |
| Supply chain | Pinned dependencies, Dependabot, CI lint and tests before every deploy |

Known trade-offs:

- TOTP secrets are stored unencrypted in the database. Protect the volume and backups.
- Someone who knows a username can trigger a 15-minute lockout for it. For a single-admin tool this
  is preferable to allowing unlimited guessing.
- The runner has Docker access on the VM. Keep the repository private and `main` protected.
