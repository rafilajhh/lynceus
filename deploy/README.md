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
git clone https://github.com/rafilajhh/lynceus.git lynceus && cd lynceus
git checkout main                      # or the branch / tag you are deploying
```

Create `/etc/lynceus.env` (outside the repo, so it cannot be committed) from the
Docker template `deploy/lynceus.env.example`, mode 600:

```bash
sudo install -m 600 deploy/lynceus.env.example /etc/lynceus.env
sudo nano /etc/lynceus.env             # replace PASTE-THE-TEAM-KEY-HERE with the real key
```

The template holds the Token Factory endpoints and models, `LOCALISATION_MODE=box`
and `LYNCEUS_ALLOW_STUB_FALLBACK=0` (hosted demo: a live-AI failure answers HTTP 503
instead of silently showing the offline stub; the sample shift stays
readable offline). It deliberately does not set `LYNCEUS_STORAGE_DIR`,
`LYNCEUS_WEB_DIR` or `LYNCEUS_BENCHMARK_DIR`: the image already points them at the
volume and the staged assets. Never feed the dev `.env.example` / `backend/.env` to
`--env-file`: it would override the storage path (the entrypoint exits with a clear
error if the storage dir is not writable).

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
    # /inspect takes a base64 photo (8 MB cap in the app); refuse bigger bodies at the edge.
    request_body {
        max_size 12MB
    }
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
about 90 s in the worst case we measured (retries under rate limiting). Caddy
has no default read timeout, so the `read_timeout 150s` above is an explicit cap,
not a fix for a default. Proxies and load balancers with short defaults do cut
these requests off: nginx (`proxy_read_timeout`, default 60 s; set
`proxy_read_timeout 150s;`) and cloud load balancers (idle timeouts are often
30-60 s; raise them to at least 120 s).

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
3. Upload a load photo with waybill text in `/app`: with the key it returns a live verdict (see step 4); the sample shift on `/shift` needs no key.
4. **Warm-up:** run one live inspection and one Pythia question yourself 10-15 minutes before judges arrive (a cold first request is the slowest, and it confirms the key works). Expect 20-35 s for the inspection; it shows "Live AMD".
5. **Key quota:** the Token Factory key is rate-limited and shared by the team. Check nobody else is running benchmarks or scripts on it; if the endpoint is throttled, live requests fail with HTTP 503 (because `LYNCEUS_ALLOW_STUB_FALLBACK=0`) and the sample shift and `/validation` still load. Do not re-run `benchmark.run` against the same key during judging.
6. Confirm `LYNCEUS_ALLOW_STUB_FALLBACK=0` is in `/etc/lynceus.env` (`docker exec lynceus printenv LYNCEUS_ALLOW_STUB_FALLBACK`).
7. Take a backup of the volume (above) after the warm-up if you want to keep those records.
8. Know the fallback: if live AI is down, present the sample shift and the `/validation` page, and say so.

## Reference

| What | Value |
|---|---|
| Image entrypoint | `deploy/entrypoint.sh` (seed if empty, then `exec python -m lynceus.main`) |
| Listening port | `$PORT`, default 8020, bound to `0.0.0.0` inside the container |
| Storage / volume | `/data/runs` (`LYNCEUS_STORAGE_DIR`) |
| Health check | `GET /health` (also the Docker `HEALTHCHECK`) |
| Runs as | unprivileged user `lynceus` (uid 10001) |
