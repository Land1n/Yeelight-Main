# Yeelight web client

This package contains the static HTML, CSS, and JavaScript browser interface
served by `yeelight_network` at `/`. It has no separate Python or native-app
process. The browser communicates with the FastAPI server; the server alone
communicates with Yeelight devices.
