# Yeelight-Network

FastAPI server exposing the Yeelight command service over HTTP.

Run with `python -m yeelight_network.server`. Configure the listening address,
port, optional API token and initial bulb IPs with the `YEELIGHT_HOST`,
`YEELIGHT_PORT`, `YEELIGHT_API_TOKEN` and `YEELIGHT_BULBS` environment
variables. In the main project these are loaded from its root `.env` file.
When bound to `0.0.0.0`, startup prints LAN URLs to open in a browser.

The server serves the browser client at `/` and static assets at `/static`.
API endpoints are available under `/api`. Protected routes accept
`X-API-Token`; the web client sends it as a request header, never in the URL.

The experimental `POST /api/provisioning/wifi` route accepts setup credentials
only from a loopback browser, checks for model `yeelink.light.color1`, and does
not persist the SSID or password. The response means the request was sent or
answered, not that the lamp joined the target network; verify by reconnecting
the computer and running discovery.
