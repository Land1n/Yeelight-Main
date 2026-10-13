# Yeelight-App

Cross-platform Flet client for Windows and Android. Run it with
`python -m yeelight_app` from the main project, or build an Android package
with `flet build apk --module-name main`.

The client connects to the HTTP API hosted by Yeelight-Network. Set
`YEELIGHT_SERVER_URL` to the server URL; use the computer's LAN IP when
connecting from a phone. Enter the API token in the client when the server
requires one. Use "Save and connect" to test the connection and store its URL
and token in the device's app preferences for later launches.
