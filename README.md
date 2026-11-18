# Link Registry

Public read-only URL list at **https://urls.yashwanthgowdam.in**. Adding, editing and deleting
needs a password plus a TOTP code from an authenticator app.

**Deployment:** push to `main` → GitHub runs the tests → GitHub SSHes into your VM as `ubuntu`,
uploads the code to `~/urls` and runs `docker compose up`. Nothing manual after setup.

Stack: Flask + gunicorn, SQLite on a Docker volume (survives every deploy), Caddy for HTTPS.

---

## Setup (once)

### 1. DNS
Add an `A` record: `urls` → your VM's public IP.

### 2. On the VM (SSH in as `ubuntu`)
```bash
sudo apt-get update && sudo apt-get -y install rsync
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow 443/udp && sudo ufw --force enable

mkdir -p ~/urls
umask 077
printf 'SECRET_KEY=%s\nCOOKIE_SECURE=1\n' "$(openssl rand -hex 32)" > ~/urls/.env
exit
```
If your cloud provider has its own firewall, open ports 22, 80, 443 (tcp) and 443 (udp) there as well.
Log in again afterwards so the Docker group applies.

### 3. GitHub
Create a **private** repo, push this project to `main`, then add three secrets under
**Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `VM_HOST` | VM public IP |
| `VM_USER` | `ubuntu` |
| `VM_SSH_KEY` | contents of the private key you already use to SSH in (e.g. `~/.ssh/id_ed25519` or your `.pem`), including the BEGIN/END lines |

That's it. The push in this step triggers the first deploy; watch it under the **Actions** tab.
The first run takes a few minutes (image build and HTTPS certificate).

### 4. Create your login (with MFA)
```bash
ssh ubuntu@<VM_IP>
cd ~/urls
docker compose exec app python -m app.cli create-user yashwanth
```
Enter a password (12+ characters) and scan the QR code with an authenticator app.

Open the site: the list is visible with no login. **Sign in to edit** asks for password, then the 6-digit code.

---

## Daily use
- **Manage links:** sign in on the website. No deploy needed.
- **Change the app:** push to `main`. Roll back by reverting the commit.
- **Logs:** `cd ~/urls && docker compose logs -f app`
- **Users:** `docker compose exec app python -m app.cli list-users | delete-user <name> | create-user <name> --force` (`--force` resets password and MFA)

## Backup and restore
Links live in the Docker volume `urls_data`; deploys never touch it.

```bash
mkdir -p ~/backups/urls
crontab -e     # add:  15 2 * * * $HOME/urls/scripts/backup.sh >> $HOME/backups/urls/backup.log 2>&1
```
Copy `~/backups/urls` off the VM now and then. Backups contain password hashes and MFA secrets.

Restore:
```bash
cd ~/urls && docker compose stop app
docker run --rm -v urls_data:/data -v $HOME/backups/urls:/b alpine sh -c \
  'rm -f /data/urls.db-wal /data/urls.db-shm && cp /b/urls-<STAMP>.db /data/urls.db && chown 10001:10001 /data/urls.db'
docker compose start app
```

## Troubleshooting
| Symptom | Fix |
|---|---|
| Deploy fails at SSH or upload | Check the three secrets; make sure `ssh ubuntu@<VM_IP>` works with that key and port 22 is open to the internet |
| `permission denied ... docker.sock` | Run `sudo usermod -aG docker ubuntu`, then log out and back in |
| Certificate error | DNS not pointing at the VM yet, or ports 80/443 blocked. `docker compose logs caddy` |
| 502 Bad Gateway | `docker compose ps`, then `docker compose logs app` |
| `SECRET_KEY must be set` | `~/urls/.env` missing or shorter than 32 characters |
| "Too many failed attempts" | 5 failures per user (20 per IP) lock sign-in for 15 minutes. Wait |
| MFA code rejected | Phone clock wrong, or code already used. Wait for the next one. Lost phone: `create-user <name> --force` |

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
CSRF tokens; strict CSP; only http/https URLs accepted; parameterised SQL; non-root, read-only
container with all capabilities dropped; HTTPS with HSTS; secrets only on the VM.

Trade-offs: TOTP secrets are stored unencrypted in the DB, and anyone who knows the username can
trigger a 15-minute lockout. The deploy job trusts the VM's SSH host key on first contact each run;
keep the repo private and `main` protected, since anyone who can change the workflow can use the key.
