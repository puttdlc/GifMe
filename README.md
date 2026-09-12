# GIFMe

A local, self-hosted GIF/animation toolkit inspired by functions of ezgif.com. Runs locally.

- **ffmpeg** - video or GIF, resize, crop, rotate/flip, speed, reverse, text
  overlay, color effects, WebP/APNG/MP4/WebM export
- **gifsicle** - GIF specific optimization
- **ImageMagick** - combining still images into an animated GIF

## What's included (tested and working)

- GIF Maker (video → GIF, images → GIF)
- Convert ( → MP4/WebM/WebP/APNG) 
- Resize, Crop, Rotate/Flip
- Speed change, Reverse
- Effects (grayscale, sepia, invert, blur, sharpen, pixelate)
- Add text overlay · Optimize (lossy compression via gifsicle)
- Split into frames (zip of PNGs)
- Analyzer (dimensions/duration/frame count/size)

## What's *not* included (ezgif has these, this doesn't yet)

- ❌ VIF and JXL support (needs `libavif`/`libjxl`, less commonly pre-installed -
straightforward to add the same way as the others, see `backend/tools.py`)
- ❌ Animated SVG import (SVG with SMIL/CSS animation really needs a headless browser to render correctly, which is a much bigger dependency)
- ❌ Batch processing multiple files in one go, and a job queue for large files (right now a request blocks until ffmpeg finishes, fine for typical GIF-sized clips but not for say a 500MB source video).


## Running It
Before running choosing options, git clone this project onto your machine.

`cd` to any folder on your machine where you'd like this project folder to be created. Run:
```
git clone https://github.com/puttdlc/GitMe.git
```
This should successfully clone this repo to your computer.
### Option A: Docker (recommended, identical on Windows/Linux/macOS)

1. Install or open up [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) or Docker Engine (Linux).

2. Ensure Docker and its service is running.

3. `cd` into the  project folder, and run:

```
docker compose up -d --build
```
This may take a few seconds to build.

*For any new updates, you can `git pull` this repo then choose to delete the docker container or simply run this command again, which will update your Docker instance to match the new version.*

4. On Docker Desktop, press run on the newly created container instance, then open **http://localhost:8000** in a browser to view the WebUI.

### Run it - Option B: natively (no Docker)

You need Python 3.10+ and ffmpeg on your PATH. The other tools are optional —
the app starts without them and says which features are unavailable.

**macOS:**
```
brew install ffmpeg                              # required
brew install gifsicle imagemagick libavif jpeg-xl  # optional
./run.sh
```

**Linux (Debian/Ubuntu):**
```
sudo apt-get install ffmpeg                                        # required
sudo apt-get install gifsicle imagemagick libavif-bin libjxl-tools # optional
./run.sh
```

**Windows** (using [Chocolatey](https://chocolatey.org/install), run as admin):
```
choco install ffmpeg              # required
choco install gifsicle imagemagick  # optional
run.bat
```

Then open **http://localhost:8000**.

## Configuring default variables

GIFMe reads its settings from environment variables - from a `.env` file
picked up automatically by `docker compose`, or exported into your shell
before running `run.sh`/`run.bat` natively (`set -a; source .env; set +a`).
There's no `.env` by default, which is equivalent to the local preset below.

Two presets are provided - copy whichever matches your situation to `.env`:

```
cp .env.local.example .env      # localhost / trusted LAN only - no auth
cp .env.selfhost.example .env   # reachable from outside your machine
```

`.env.selfhost.example` requires you to set a real `GIFME_USERNAME` /
`GIFME_PASSWORD` before it does anything useful, leaving either blank
disables auth entirely. If you skip creating a `.env` file altogether,
`docker-compose.yml` falls back to the selfhost-shaped defaults below
(minus auth, which stays off until you set it) rather than the local ones.

| Variable | selfhost preset | local preset | Purpose |
|---|---|---|---|
| `GIFME_USERNAME` / `GIFME_PASSWORD` | *(you fill in)* | unset | Set **both** to require HTTP Basic auth on every request. Strongly recommended for anything internet-facing. |
| `GIFME_MAX_UPLOAD_MB` | `500` | `0` (unlimited) | Rejects uploads larger than this. |
| `GIFME_JOB_TTL_HOURS` | `24` | `0` (never) | A job's uploads/outputs are deleted this many hours after they were last touched, so disk usage stays bounded. |
| `GIFME_ALLOWED_ORIGINS` | unset | unset | Comma-separated origins allowed to call `/api/*` cross-origin. Leave unset unless you're serving the frontend from a different domain than the API. |
| `HOST_WORKDIR` | *(docker only)* | *(docker only)* | What the "Output Folder" button reports, since the container can't open a file manager on your host. |

Editing an existing `.env`? Recreate the container so it picks up the
change. Stopping/starting or pausing/unpausing in Docker Desktop reuses
the running container as-is and won't re-read it:
```
docker compose up -d
```


## Self-Host (expose it on your own domain)

GIFMe has no login and no per-file access checks by default, which is typically fine on a localhost.

Set up the `.env.selfhost.example` preset above before doing any of the below, since
this is meant to run one instance per household/team rather than serve
untrusted random strangers. A basic auth (or an access layer in front, like
Cloudflare Access) is enough.

### Deploying behind a Cloudflare Tunnel

This gets you `https://gif.yourdomain.com` pointed at GIFMe running on any
machine you control (a VPS, a home server, a Raspberry Pi) and no port
forwarding, no separate TLS certificate, and the origin port never has to
be exposed to the internet directly.

1. On the host machine, `cp .env.selfhost.example .env` and set
   `GIFME_USERNAME`/`GIFME_PASSWORD` in it, then bring the app up:
   ```
   docker compose up -d --build
   ```
   By default `docker-compose.yml` binds the container's port to
   `127.0.0.1:8000` on the host - reachable only via the tunnel, not the
   open network.

2. Install `cloudflared` on the same machine ([docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/)),
   then authenticate it against your Cloudflare account and domain:
   ```
   cloudflared tunnel login
   cloudflared tunnel create gifme
   ```

3. Route a hostname to the tunnel and point the tunnel at the local app:
   ```
   cloudflared tunnel route dns gifme gif.yourdomain.com
   ```
   ```yaml
   # ~/.cloudflared/config.yml
   # cloudflared tunnel config template
   # Optimized for mid-size file transfers (10-100MB range): no chunked encoding,
   # warm keepalive pool, relaxed timeouts. Replace the placeholders below.

   tunnel: <TUNNEL_NAME>
   credentials-file: /home/<USER>/.cloudflared/<TUNNEL_UUID>.json

   originRequest:
     connectTimeout: 10s
     tcpKeepAlive: 30s
     keepAliveConnections: 100
     keepAliveTimeout: 90s
     disableChunkedEncoding: true   # requires origin to send Content-Length
     noHappyEyeballs: true          # safe to leave true for localhost origins
     http2Origin: false

   ingress:
     - hostname: <SUBDOMAIN>.<DOMAIN>
       service: http://localhost:<PORT>
     # Add more hostname/service blocks here for additional services on this tunnel:
     # - hostname: <OTHER_SUBDOMAIN>.<DOMAIN>
     #   service: http://localhost:<OTHER_PORT>
     - service: http_status:404
   ```

4. Run it as a service so it survives reboots:
   ```
   sudo cloudflared service install
   sudo systemctl enable --now cloudflared
   ```

5. Open `https://gif.yourdomain.com` - Cloudflare handles TLS for you.

Any other reverse proxy (Caddy, Nginx, Traefik) works the same way: proxy
to `http://127.0.0.1:8000` and terminate TLS in front of it. GIFMe doesn't
need to know it's behind a proxy. There is no cookie/redirect logic tied to
a specific host or scheme.

**Sizing note:** ffmpeg/gifsicle/ImageMagick are CPU and memory-bound, and
a request blocks until the conversion finishes (see "What's *not*
included" above). A small VPS is fine for personal use, but concurrent
users converting large videos will queue behind each other.

### Hosting somewhere other than Cloudflare

GIFMe is just a Docker container (or a plain `uvicorn` process) - any host
that can run one works. Cloudflare Tunnel is documented above because it's
free and needs no open ports, but it's not required. Roughly in order of
how much infrastructure you're taking on yourself:

- **Another tunnel service**, same idea as Cloudflare Tunnel (no port
  forwarding, no separate TLS setup): [Tailscale Funnel](https://tailscale.com/kb/1223/funnel)
  exposes it through your existing Tailnet; [ngrok](https://ngrok.com/) gives
  a quick public URL, handy for testing but rate-limited/ephemeral on the
  free tier.

- **A VPS you manage** (DigitalOcean, Hetzner, Linode, AWS Lightsail, etc.):
  point your domain's DNS at the box, run `docker compose up -d` there, and
  put a reverse proxy in front for TLS - [Caddy](https://caddyserver.com/)
  is the least setup (automatic Let's Encrypt certs from a ~5-line
  Caddyfile); Nginx or Traefik work too if you already use them. Since
  nothing is tunneling the connection for you here, only open 80/443 on the
  box's firewall and let the proxy forward to `127.0.0.1:8000` - don't
  expose port 8000 to the internet directly.

- **A container PaaS** (Fly.io, Railway, Render, etc.): these can usually
  build straight from this repo's `Dockerfile`. Set the
  `.env.selfhost.example` variables in the platform's env var UI, and
  attach a persistent volume at `/app/backend/workdir` if it offers one -
  otherwise every redeploy wipes in-progress jobs. Skip anything
  serverless/functions-based (Cloudflare Workers/Pages, Vercel, Lambda):
  GIFMe needs a long-running process with ffmpeg/gifsicle/ImageMagick
  installed and a writable disk, which those platforms don't give you.

- **A home server behind your own router**: port-forward 443 to the
  machine, get a TLS cert (Caddy or `certbot`), and add a dynamic DNS
  service if your ISP doesn't hand you a static IP.

Whichever route you pick, the same rules from the top of this section still
apply - use the `.env.selfhost.example` preset, keep the app bound to
localhost/a private network behind whatever terminates TLS, and size the
machine for ffmpeg's CPU/memory use.