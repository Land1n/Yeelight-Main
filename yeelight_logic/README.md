# Yeelight-Logic

Logic layer for Yeelight LAN control. It validates console commands, discovers
bulbs and delegates device operations through a typed adapter interface.

The package can be tested without physical bulbs by injecting a `bulb_factory`
and a discovery function into `YeelightController`.

Supported commands include `discover`, `list`, `add`, `remove`, `status`, `on`,
`off`, `toggle`, `brightness`, `color` and `temp`.
