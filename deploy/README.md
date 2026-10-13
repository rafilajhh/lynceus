# Deploying Lynceus on your own server

One container serves the API and the built UI. The AMD Token Factory key is
passed at run time and is never part of the image. The build, run, seeding, restart and
health-check steps below were exercised locally with Docker 29; the proxy and
server steps were not, since nothing in this repository deploys anywhere for you.

## Prerequisites

- A Linux server with Docker (Engine 24+ is fine) and at least 1 GB free RAM.
- A domain name pointing at the server (needed for automatic HTTPS), or just its
  IP for plain HTTP testing.
- Ports 80 and 443 open (for the reverse proxy). The app itself listens on 8020
  and does not need to be public.
- The team's AMD Token Factory key (`notebooks.amd.com/tokenfactory`).

## 1. Get the code and write the env file

```bash
git clone <your repo url> lynceus && cd lynceus
git checkout feat/lynceus-1.0          # or the branch / tag you are deploying
```

Create `/etc/lynceus.env` (outside the repo, so it cannot be committed), mode 600:

```bash
sudo install -m 600 /dev/null /etc/lynceus.env
sudo tee /etc/lynceus.env >/dev/null <<'EOF'
VLLM_VLM_URL=https://developer.amd.com.cn/radeon/api/v1
VLLM_LLM_URL=https://developer.amd.com.cn/radeon/api/v1
VLM_MODEL=MiniCPM-V-4.7-35B-A3B
LLM_MODEL=DeepSeek-V4-Flash
ASSIST_URL=https://developer.amd.com.cn/radeon/api/v1
ASSIST_MODEL=DeepSeek-V4-Flash
LOCALISATION_MODE=box
VLLM_API_KEY=PASTE-THE-TEAM-KEY-HERE
# Hosted demo: when the live AI fails, answer HTTP 503 instead of silently showing
# the offline stub. The scripted demo buttons (green/amber/red) keep working.
LYNCEUS_ALLOW_STUB_FALLBACK=0
EOF
sudo nano /etc/lynceus.env             # paste the real key
```

Do not use quotes around values and do not put the key in the shell history or
in the Dockerfile.

## 2. Build and run

```bash
docker build -t lynceus:latest .

docker run -d --name lynceus \
  --restart unless-stopped \
  --env-file /etc/lynceus.env \
  -p 127.0.0.1:8020:8020 \
  -v lynceus-runs:/data/runs \
  lynceus:latest
```

- `-p 127.0.0.1:8020:8020` keeps the app reachable only through the reverse
  proxy below. For a quick test without a proxy use `-p 8020:8020`.
- `-v lynceus-runs:/data/runs` is a named volume holding the audit records. Use
  a named volume (not a bind mount): the container runs as an unprivileged user
  and the volume inherits the right ownership.
- On the first start the storage is empty, so the entrypoint seeds the 24-truck
  sample shift (offline, no key used). On later starts it finds the records and
  skips seeding.

Check it:

```bash
docker ps                                   # STATUS should become "healthy"
curl -s localhost:8020/health               # {"status":"ok",...}
curl -s localhost:8020/benchmark/latest | head -c 300
```

## 3. HTTPS with Caddy (reverse proxy)

Install Caddy (<https://caddyserver.com/docs/install>), then `/etc/caddy/Caddyfile`:

```
your.domain.example {
    reverse_proxy 127.0.0.1:8020 {
        transport http {
            read_timeout 150s
        }
    }
}
```

```bash
sudo systemctl reload caddy
```

Caddy obtains and renews the certificate itself. **Keep the proxy read timeout
at 120 s or more**: a live inspection takes about 20-35 s typically and up to
about 90 s in the worst case we measured (retries under rate limiting). A
default 30-60 s proxy timeout will cut those requests off. With nginx the
equivalent is `proxy_read_timeout 150s;`.

## Updating

```bash
cd lynceus
git pull
docker build -t lynceus:latest .
docker rm -f lynceus
docker run -d --name lynceus --restart unless-stopped \
  --env-file /etc/lynceus.env -p 127.0.0.1:8020:8020 \
  -v lynceus-runs:/data/runs lynceus:latest
```

The volume is kept, so records survive the update and no re-seeding happens.

## Logs and status

```bash
docker logs -f lynceus                  # uvicorn + seed messages
docker inspect --format '{{.State.Health.Status}}' lynceus
docker stats --no-stream lynceus
```

## Backup and restore of the records

```bash
# backup
docker run --rm -v lynceus-runs:/data -v "$PWD":/backup alpine \
  tar czf /backup/lynceus-runs-$(date +%F).tgz -C /data .

# restore (into an empty volume, before starting the container)
docker volume create lynceus-runs
docker run --rm -v lynceus-runs:/data -v "$PWD":/backup alpine \
  sh -c 'tar xzf /backup/lynceus-runs-YYYY-MM-DD.tgz -C /data && chown -R 10001:10001 /data'
```

## Reset to the sample shift

Wipe the records and let the next start re-seed (this deletes every stored
inspection, including any live ones made during judging):

```bash
docker rm -f lynceus
docker volume rm lynceus-runs
# then the same `docker run ...` as above: empty volume -> sample shift is seeded
```

Back up first (above) if you want to keep the live records.

## Judging-day checklist

1. `docker ps` shows `lynceus` as `healthy`; `curl -s https://your.domain.example/health` returns `"status":"ok"`.
2. Open `/`, `/app`, `/shift` (sample shift shows 24 trucks), `/inspections`, `/validation` in a browser; each loads.
3. Click the three scripted demo cases (green / amber / red): they work without the key and show "Scripted sample".
4. **Warm-up:** run one live inspection and one Pythia question yourself 10-15 minutes before judges arrive (a cold first request is the slowest, and it confirms the key works). Expect 20-35 s for the inspection; it shows "Live AMD".
5. **Key quota:** the Token Factory key is rate-limited and shared by the team. Check nobody else is running benchmarks or scripts on it; if the endpoint is throttled, live requests fail with HTTP 503 (because `LYNCEUS_ALLOW_STUB_FALLBACK=0`) and the scripted demo cases still work. Do not re-run `benchmark.run` against the same key during judging.
6. Confirm `LYNCEUS_ALLOW_STUB_FALLBACK=0` is in `/etc/lynceus.env` (`docker exec lynceus printenv LYNCEUS_ALLOW_STUB_FALLBACK`).
7. Take a backup of the volume (above) after the warm-up if you want to keep those records.
8. Know the fallback: if live AI is down, present the scripted cases and the `/validation` page, and say so.

## Reference

| What | Value |
|---|---|
| Image entrypoint | `deploy/entrypoint.sh` (seed if empty, then `exec python -m lynceus.main`) |
| Listening port | `$PORT`, default 8020, bound to `0.0.0.0` inside the container |
| Storage / volume | `/data/runs` (`LYNCEUS_STORAGE_DIR`) |
| Health check | `GET /health` (also the Docker `HEALTHCHECK`) |
| Runs as | unprivileged user `lynceus` (uid 10001) |
