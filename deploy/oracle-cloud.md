# Deploying to an Oracle Cloud Always Free VM

Oracle's Always Free tier does not expire after 12 months, which is why it is
used here rather than the AWS free tier. The ARM (Ampere A1) shape gives you up
to 4 cores and 24 GB of RAM for nothing, which is far more than this needs.

Everything below is done once. After that, pushing to `master` redeploys.

---

## 1. Create the VM

1. Sign up at <https://cloud.oracle.com>. A card is required for identity
   verification; Always Free resources are not charged against it.
2. **Compute → Instances → Create instance.**
3. Change the image and shape:
   - **Image:** Canonical Ubuntu 22.04
   - **Shape:** `VM.Standard.A1.Flex` (Ampere ARM), 1–2 OCPU, 6–12 GB RAM
   - Confirm the shape is labelled **Always Free eligible**
4. Under **Add SSH keys**, choose *Generate a key pair* and download the
   private key — Oracle will not show it again.
5. Create the instance and note its **public IP address**.

> If instance creation fails with "out of host capacity", the ARM shape is
> temporarily exhausted in that region. Either retry later or fall back to
> `VM.Standard.E2.1.Micro` (x86), which is also Always Free.

## 2. Open the firewall

Oracle blocks inbound traffic at two layers, and both must be opened.

**Cloud firewall:** on the instance page, follow *Primary VNIC → Subnet →
Security List → Add Ingress Rule*:

| Field | Value |
| --- | --- |
| Source CIDR | `0.0.0.0/0` |
| IP Protocol | TCP |
| Destination Port Range | `8000` |

**Host firewall:** Ubuntu images on Oracle ship with restrictive iptables
rules, so also run on the VM:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save
```

Forgetting the second step is the single most common reason the dashboard is
unreachable while the container looks perfectly healthy.

## 3. Install Docker

```bash
chmod 600 ~/Downloads/ssh-key.key
ssh -i ~/Downloads/ssh-key.key ubuntu@YOUR_PUBLIC_IP
```

```bash
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker          # apply the group without logging out
docker --version
```

## 4. Run the application

```bash
git clone https://github.com/chanllawala/uptime-monitor.git
cd uptime-monitor

cp .env.example .env
nano .env             # paste your Slack webhook URL, then save
```

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f worker
```

Seed the starter monitors (optional):

```bash
docker compose exec web python -m app.seed
```

The dashboard is now at `http://YOUR_PUBLIC_IP:8000`.

## 5. Wire up automatic deploys

In the GitHub repository, under **Settings → Secrets and variables → Actions**:

**Secrets:**

| Name | Value |
| --- | --- |
| `DEPLOY_HOST` | the VM's public IP |
| `DEPLOY_USER` | `ubuntu` |
| `DEPLOY_SSH_KEY` | the full contents of the private key file |

**Variables:**

| Name | Value |
| --- | --- |
| `DEPLOY_ENABLED` | `true` |

The deploy job is gated on `DEPLOY_ENABLED`, so CI stays green before the VM
exists and starts deploying the moment that variable is set.

## Operating it

```bash
docker compose logs -f worker     # watch checks as they happen
docker compose restart worker     # pick up .env changes
docker compose down               # stop (data survives in the pgdata volume)
docker compose down -v            # stop and erase all history
```

Back up the database:

```bash
docker compose exec db pg_dump -U uptime uptime > backup-$(date +%F).sql
```

## Optional hardening

Exposing port 8000 directly is fine for a demo but has no TLS and no access
control. To put it behind HTTPS on a real domain, add Caddy in front — it
obtains and renews Let's Encrypt certificates automatically:

```yaml
  caddy:
    image: caddy:2-alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
    depends_on: [web]
```

With a `Caddyfile` of:

```
monitor.yourdomain.com {
    reverse_proxy web:8000
}
```

Then close port 8000 in the security list, leaving only 80 and 443 open.
