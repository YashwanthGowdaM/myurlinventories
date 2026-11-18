# Link Registry

Public read-only URL list at **https://urls.yashwanthgowdam.in**. Adding, editing and deleting
needs a password plus a TOTP code from an authenticator app.

**Everything is done by the GitHub workflow. You never SSH in to set up or deploy.**

## What you do (once)

1. **DNS:** add an `A` record `urls` → your VM's public IP.
2. **Cloud firewall:** allow inbound TCP 22, 80, 443 and UDP 443 on the VM. This lives at your
   cloud provider, so a workflow cannot do it for you.
3. **GitHub secrets:** create a private repo, push this project, then add five secrets under
   **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `VM_HOST` | VM public IP |
| `VM_USER` | `ubuntu` |
| `VM_SSH_KEY` | contents of the private key you already use to SSH in, including BEGIN/END lines |
| `ADMIN_USERNAME` | login name for the site, e.g. `yashwanth` |
| `ADMIN_PASSWORD` | password for the site, 12+ characters |

4. **Push to `main`.** That's the deployment.

## What the workflow does on every run

| Step | Result |
|---|---|
| test | Lint, unit tests and a Docker build on GitHub. A failure stops the deploy |
| Prepare VM | Installs Docker and rsync if missing; creates `~/urls/.env` with a random `SECRET_KEY` only if it does not exist; opens ports 80/443 only if `ufw` is already active; installs a nightly backup cron |
| Upload code | `rsync` to `~/urls` on the VM, never touching `.env` |
| Build and restart | `docker compose up -d --build --wait`, then reloads Caddy |
| Ensure admin | Creates your admin account on the first run only |
| Smoke test | Calls `/healthz` over HTTPS |

Every step is safe to repeat. The database lives in a Docker volume and survives all deploys.

## First login (MFA setup)

On the **first successful run** the "Ensure admin account" step prints a block like this in the job log:

```
=== Authenticator setup ===
Account : <your username>
Key     : ABCD EFGH ...
Type    : time-based (TOTP), 6 digits, 30 seconds
```

Open your authenticator app → **Add account → Enter a setup key**, type the key, then sign in at
the website with your username, password and the 6-digit code.

That key is a secret and the log is readable by anyone with access to the repo. After you have
added it, delete the log: **Actions → that run → ⋯ → Delete all logs**. It is printed only when the
account is created or reset, never on normal deploys.

## Reset password or lost phone

1. Change the `ADMIN_PASSWORD` secret if you want a new password.
2. **Actions → ci-cd → Run workflow →** tick **Reset the admin password and MFA** → Run.
3. Take the new key from the log, as above.

## Daily use

- **Manage links:** sign in on the website. No deploy needed.
- **Change the app:** push to `main`. Roll back by reverting the commit.

## Backups

The workflow installs a cron job that writes a database copy to `~/backups/urls` every night and
keeps 14. These stay on the VM, so also snapshot the VM or copy that folder elsewhere.
Backups contain password hashes and MFA secrets.

## Troubleshooting (read the failed step in Actions)

| Failed step | Likely cause |
|---|---|
| Configure SSH / Prepare VM | Wrong `VM_HOST`, `VM_USER` or `VM_SSH_KEY`; port 22 closed in the cloud firewall; user has no passwordless sudo |
| Build and restart | Read the error; usually a build or Docker problem |
| Ensure admin account | `ADMIN_PASSWORD` shorter than 12 characters, or `ADMIN_USERNAME` has invalid characters |
| Smoke test | DNS not pointing at the VM yet, or ports 80/443 blocked. Fix it, then **Re-run failed jobs** |
| Site shows a certificate error | Same as above; Caddy retries automatically once DNS and ports are right |

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
container with all capabilities dropped; HTTPS with HSTS; the session key exists only on the VM.

Trade-offs: TOTP secrets are stored unencrypted in the DB; anyone who knows the username can trigger
a 15-minute lockout; the deploy job trusts the VM's SSH host key on first contact each run. Keep the
repo private and `main` protected, because anyone who can change the workflow can use your SSH key
and see the admin password secret in use.
