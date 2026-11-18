# Link Registry

Public read-only URL list at **https://urls.yashwanthgowdam.in**. Adding, editing and deleting
needs a password plus a TOTP code from an authenticator app.

**How deployment works:** you push to `main`. GitHub runs the tests, then logs into your VM over
SSH, uploads the code and runs `docker compose up`. You never deploy by hand.

Stack: Flask + gunicorn, SQLite on a Docker volume (survives every deploy), Caddy for HTTPS.

---

## Setup (do once)

### 1. DNS
Add an `A` record: `urls` → your VM's public IP. Check with `dig +short urls.yashwanthgowdam.in`.

### 2. Prepare the VM (Ubuntu 22.04/24.04)
SSH in as an admin user and run:

```bash
sudo apt-get update && sudo apt-get -y install curl rsync ufw
curl -fsSL https://get.docker.com | sudo sh

sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy
sudo install -d -o deploy -g deploy /opt/urls

sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow 443/udp
sudo ufw enable
```
If your cloud provider has its own firewall, open ports 22, 80, 443 (tcp) and 443 (udp) there too.

### 3. Create a deploy SSH key
On **your laptop**:

```bash
ssh-keygen -t ed25519 -f urls-deploy-key -N "" -C "github-actions-urls"
ssh-copy-id -i urls-deploy-key.pub deploy@<VM_IP>      # or append the .pub file to /home/deploy/.ssh/authorized_keys
ssh -i urls-deploy-key deploy@<VM_IP> 'docker ps'      # must work without a password
ssh-keyscan -H <VM_IP>                                 # copy this output for the VM_KNOWN_HOSTS secret
```

### 4. Create the secret key on the VM
```bash
ssh deploy@<VM_IP>
umask 077
printf 'SECRET_KEY=%s\nCOOKIE_SECURE=1\n' "$(openssl rand -hex 32)" > /opt/urls/.env
exit
```

### 5. Add GitHub secrets
Create a **private** repo and push this project to `main`. Then go to
**Settings → Secrets and variables → Actions → New repository secret** and add:

| Name | Value |
|---|---|
| `VM_HOST` | VM public IP |
| `VM_USER` | `deploy` |
| `VM_SSH_KEY` | full contents of `urls-deploy-key` (the private key, including BEGIN/END lines) |
| `VM_KNOWN_HOSTS` | output of `ssh-keyscan -H <VM_IP>` |

Delete `urls-deploy-key` from your laptop once it is stored in the secret (or keep it in a password manager).

### 6. Deploy
Push to `main` (or **Actions → ci-cd → Re-run all jobs**). First run takes a few minutes while the
image builds and Caddy gets a certificate. Check **Actions** for a green run.

### 7. Create your admin user (with MFA)
```bash
ssh deploy@<VM_IP>
cd /opt/urls/app
docker compose exec app python -m app.cli create-user yashwanth
```
Enter a password (12+ characters), then scan the QR code with your authenticator app.
Other commands: `list-users`, `delete-user <name>`, `create-user <name> --force` (reset password and MFA).

### 8. Check it works
Open the site in a private window: you see the list, no login needed, no edit buttons.
Click **Sign in to edit**, enter password then the 6-digit code, add a link.

---

## Daily use
- **Manage links:** sign in on the website. No deploy needed.
- **Change the app:** edit code, push to `main`, it deploys itself.
- **Roll back:** revert the commit on `main` and push.
- **Logs:** `docker compose -f /opt/urls/app/docker-compose.yml logs -f app`

## Backup and restore
Data is in the Docker volume `urls_data`. Only `docker compose down -v` deletes it.

```bash
sudo install -d -o deploy -g deploy -m 700 /var/backups/urls
crontab -e     # as deploy, add:  15 2 * * * /opt/urls/app/scripts/backup.sh >> /var/backups/urls/backup.log 2>&1
```
Copy `/var/backups/urls` off the VM regularly. Backups contain password hashes and MFA secrets.

Restore:
```bash
cd /opt/urls/app && docker compose stop app
docker run --rm -v urls_data:/data -v /var/backups/urls:/b alpine sh -c \
  'rm -f /data/urls.db-wal /data/urls.db-shm && cp /b/urls-<STAMP>.db /data/urls.db && chown 10001:10001 /data/urls.db'
docker compose start app
```

## Troubleshooting
| Symptom | Fix |
|---|---|
| Deploy fails at "Configure SSH" or "Upload code" | Check the four secrets; test `ssh -i urls-deploy-key deploy@<VM_IP>` manually; port 22 must be reachable from the internet |
| `permission denied ... docker.sock` | `sudo usermod -aG docker deploy`, then log out and in again |
| Certificate error in browser | DNS not pointing at the VM yet, or ports 80/443 blocked. `docker compose logs caddy` |
| 502 Bad Gateway | `docker compose ps` then `docker compose logs app` |
| `SECRET_KEY must be set` | `/opt/urls/.env` missing or too short (needs 32+ characters) |
| "Too many failed attempts" | 5 failures per user (20 per IP) lock sign-in for 15 minutes. Wait |
| MFA code rejected | Phone clock wrong, or code already used. Wait for the next code. Lost phone: `create-user <name> --force` |

## Local development
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest && ruff check .
export DATA_DIR=./data COOKIE_SECURE=0 SECRET_KEY=$(openssl rand -hex 32)
python -m app.cli create-user dev && flask --app app run --debug
```

## Security summary
Argon2id passwords; TOTP MFA with replay protection; login throttling; hardened session cookies;
CSRF tokens on every change; strict CSP; only http/https URLs accepted; parameterised SQL;
non-root, read-only container with all capabilities dropped; HTTPS with HSTS; secrets only on the VM.

Trade-offs: TOTP secrets are stored unencrypted in the DB (protect the volume and backups), and
anyone who knows the username can cause a 15-minute lockout. Use a dedicated SSH key for deploys,
and keep the repo private and `main` protected.
