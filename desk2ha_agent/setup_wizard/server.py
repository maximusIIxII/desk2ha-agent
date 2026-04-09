"""Setup wizard web server.

On first run (no config file), the agent starts a minimal HTTP server
that serves a setup wizard at http://localhost:9693/setup.  The wizard
asks for a pairing code, discovers HA via mDNS, phones home, writes
config.toml, and restarts the agent in normal mode.
"""

from __future__ import annotations

import logging
import platform
import socket
import webbrowser
from pathlib import Path
from string import Template

from aiohttp import web

logger = logging.getLogger(__name__)

_DEFAULT_PORT = 9693


async def run_setup_wizard(
    config_dir: Path,
    port: int = _DEFAULT_PORT,
) -> bool:
    """Serve the setup wizard and wait until pairing is complete.

    Returns True if setup was successful.
    """
    setup_complete = False

    async def handle_index(request: web.Request) -> web.Response:
        html = _SETUP_HTML.safe_substitute(port=port)
        return web.Response(text=html, content_type="text/html")

    async def handle_pair(request: web.Request) -> web.Response:
        nonlocal setup_complete
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)

        code = data.get("code", "").strip().upper()
        if not code or len(code) < 4:
            return web.json_response({"error": "Invalid pairing code"}, status=400)

        # Discover HA instances via mDNS
        ha_instances = await _discover_ha(timeout=5.0)
        if not ha_instances:
            return web.json_response(
                {
                    "error": "No Home Assistant found on your network. "
                    "Make sure HA is running and on the same network."
                },
                status=404,
            )

        # Try pairing code against each HA instance
        import aiohttp as aio

        for ha_url in ha_instances:
            try:
                async with (
                    aio.ClientSession(timeout=aio.ClientTimeout(total=10)) as session,
                    session.post(
                        f"{ha_url}/desk2ha/install/pair",
                        json={
                            "pairing_code": code,
                            "agent_url": f"http://{_get_local_ip()}:{port}",
                            "hardware": _get_hardware_info(),
                        },
                    ) as resp,
                ):
                    if resp.status == 200:
                        result = await resp.json()
                        # Write config
                        _write_config(
                            config_dir,
                            agent_token=result.get("agent_token", ""),
                            ha_url=ha_url,
                            phone_home_token=result.get("phone_home_token", ""),
                            port=port,
                        )
                        setup_complete = True
                        return web.json_response(
                            {
                                "status": "ok",
                                "message": f"Connected to {ha_url}",
                            }
                        )
            except Exception:
                continue

        return web.json_response(
            {
                "error": f"Pairing code '{code}' not recognized. "
                "Check the code in Home Assistant and try again."
            },
            status=403,
        )

    async def handle_status(request: web.Request) -> web.Response:
        return web.json_response({"setup_complete": setup_complete})

    app = web.Application()
    app.router.add_get("/setup", handle_index)
    app.router.add_post("/setup/pair", handle_pair)
    app.router.add_get("/setup/status", handle_status)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()

    logger.info("Setup wizard running at http://localhost:%d/setup", port)

    # Open browser
    import contextlib

    with contextlib.suppress(Exception):
        webbrowser.open(f"http://localhost:{port}/setup")

    # Wait for setup to complete (polled by the caller)
    import asyncio

    while not setup_complete:
        await asyncio.sleep(1)

    await runner.cleanup()
    return True


async def _discover_ha(timeout: float = 5.0) -> list[str]:
    """Discover Home Assistant instances via mDNS."""
    urls: list[str] = []
    try:
        import asyncio

        from zeroconf import ServiceBrowser, Zeroconf

        zc = Zeroconf()
        found: list[tuple[str, int]] = []

        class Listener:
            def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
                info = zc.get_service_info(type_, name)
                if info and info.addresses:
                    ip = socket.inet_ntoa(info.addresses[0])
                    found.append((ip, info.port or 8123))

            def remove_service(self, *args: object) -> None:
                pass

            def update_service(self, *args: object) -> None:
                pass

        browser = ServiceBrowser(zc, "_home-assistant._tcp.local.", Listener())
        await asyncio.sleep(timeout)
        browser.cancel()
        zc.close()

        for ip, port in found:
            urls.append(f"http://{ip}:{port}")
    except ImportError:
        logger.debug("zeroconf not available, trying common addresses")

    # Fallback: try common HA addresses
    if not urls:
        import aiohttp as aio

        for addr in ["homeassistant.local:8123", "homeassistant:8123"]:
            try:
                async with (
                    aio.ClientSession(timeout=aio.ClientTimeout(total=3)) as session,
                    session.get(f"http://{addr}/api/") as resp,
                ):
                    if resp.status in (200, 401):
                        urls.append(f"http://{addr}")
            except Exception:
                pass

    return urls


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def _get_hardware_info() -> dict[str, str]:
    info: dict[str, str] = {
        "hostname": socket.gethostname(),
        "os": platform.system(),
        "machine": platform.machine(),
    }
    # Best-effort manufacturer/model
    if platform.system() == "Windows":
        try:
            import subprocess

            for key in ("manufacturer", "model"):
                r = subprocess.run(
                    ["wmic", "computersystem", "get", key, "/value"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                for line in r.stdout.splitlines():
                    if "=" in line:
                        info[key] = line.split("=", 1)[1].strip()
        except Exception:
            pass
    elif platform.system() == "Darwin":
        try:
            import subprocess

            r = subprocess.run(
                ["sysctl", "-n", "hw.model"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            info["manufacturer"] = "Apple"
            info["model"] = r.stdout.strip()
        except Exception:
            pass
    else:
        try:
            info["manufacturer"] = Path("/sys/class/dmi/id/sys_vendor").read_text().strip()
            info["model"] = Path("/sys/class/dmi/id/product_name").read_text().strip()
        except Exception:
            pass
    return info


def _write_config(
    config_dir: Path,
    agent_token: str,
    ha_url: str,
    phone_home_token: str,
    port: int,
) -> None:
    """Write the agent config.toml."""
    config_dir.mkdir(parents=True, exist_ok=True)
    config = f"""\
# Desk2HA Agent — auto-configured via setup wizard
[agent]
device_name = "auto"

[http]
enabled = true
bind = "0.0.0.0"
port = {port}
auth_token = "{agent_token}"

[provisioning]
phone_home_url = "{ha_url}/desk2ha/install/phone-home"
phone_home_token = "{phone_home_token}"

[logging]
level = "INFO"
"""
    path = config_dir / "config.toml"
    path.write_text(config, encoding="utf-8")
    logger.info("Config written to %s", path)


_SETUP_HTML = Template("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Desk2HA Setup</title>
<style>
  :root { --blue: #03A9F4; --dark: #1a1a2e; --card: #16213e; --text: #e0e0e0;
          --green: #4CAF50; --red: #f44336; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: var(--dark); color: var(--text); min-height: 100vh;
         display: flex; justify-content: center; align-items: center; padding: 2rem; }
  .container { max-width: 480px; width: 100%; text-align: center; }
  .logo { font-size: 3rem; margin-bottom: 0.5rem; }
  h1 { color: var(--blue); font-size: 1.6rem; margin-bottom: 0.3rem; }
  .subtitle { color: #888; margin-bottom: 2rem; font-size: 0.95rem; }
  .card { background: var(--card); border-radius: 16px; padding: 2rem;
          border: 1px solid #2a2a4a; }
  label { display: block; text-align: left; color: #aaa; font-size: 0.85rem;
          margin-bottom: 0.5rem; }
  input { width: 100%; padding: 1rem; font-size: 1.4rem; text-align: center;
          letter-spacing: 0.3rem; text-transform: uppercase;
          background: #0d1117; border: 2px solid #30363d; border-radius: 12px;
          color: var(--blue); font-family: 'SF Mono', 'Fira Code', monospace;
          outline: none; transition: border-color 0.2s; }
  input:focus { border-color: var(--blue); }
  input::placeholder { letter-spacing: 0.1rem; font-size: 1rem; color: #444; }
  .btn { width: 100%; padding: 1rem; margin-top: 1.2rem; font-size: 1rem;
         font-weight: 600; border: none; border-radius: 12px; cursor: pointer;
         background: var(--blue); color: #fff; transition: all 0.2s; }
  .btn:hover { background: #0288D1; transform: translateY(-1px); }
  .btn:disabled { background: #333; color: #666; cursor: not-allowed; transform: none; }
  .status { margin-top: 1rem; min-height: 2rem; font-size: 0.95rem; }
  .status.error { color: var(--red); }
  .status.success { color: var(--green); }
  .status.info { color: var(--blue); }
  .help { margin-top: 2rem; color: #555; font-size: 0.85rem; line-height: 1.5; }
  .spinner { display: inline-block; width: 1rem; height: 1rem;
             border: 2px solid #444; border-top: 2px solid var(--blue);
             border-radius: 50%; animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .success-icon { font-size: 3rem; margin-bottom: 1rem; }
</style>
</head>
<body>
<div class="container">
  <div class="logo">&#128421;</div>
  <h1>Desk2HA Agent Setup</h1>
  <p class="subtitle">Connect this computer to Home Assistant</p>

  <div class="card" id="setup-card">
    <label for="code">Enter the pairing code from Home Assistant:</label>
    <input type="text" id="code" maxlength="8" placeholder="ABC-123"
           autocomplete="off" autofocus>
    <button class="btn" id="pair-btn" onclick="pair()">Connect</button>
    <div class="status" id="status"></div>
  </div>

  <div class="card" id="success-card" style="display:none">
    <div class="success-icon">&#9989;</div>
    <h2 style="color:var(--green);margin-bottom:0.5rem">Connected!</h2>
    <p style="color:#aaa">This computer is now linked to Home Assistant.<br>
    You can close this window.</p>
  </div>

  <p class="help">
    Open Home Assistant &rarr; Settings &rarr; Devices &amp; Services &rarr;
    Add Integration &rarr; Desk2HA &rarr; "Distribute agent" to get the code.
  </p>
</div>

<script>
const codeInput = document.getElementById('code');
const pairBtn = document.getElementById('pair-btn');
const status = document.getElementById('status');

codeInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') pair();
});

async function pair() {
  const code = codeInput.value.trim();
  if (!code) { show('Please enter a pairing code', 'error'); return; }

  pairBtn.disabled = true;
  show('<span class="spinner"></span> Connecting to Home Assistant...', 'info');

  try {
    const resp = await fetch('/setup/pair', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({code})
    });
    const data = await resp.json();
    if (resp.ok) {
      document.getElementById('setup-card').style.display = 'none';
      document.getElementById('success-card').style.display = 'block';
    } else {
      show(data.error || 'Pairing failed', 'error');
      pairBtn.disabled = false;
    }
  } catch(e) {
    show('Connection error: ' + e.message, 'error');
    pairBtn.disabled = false;
  }
}

function show(msg, type) {
  status.innerHTML = msg;
  status.className = 'status ' + type;
}
</script>
</body>
</html>
""")
