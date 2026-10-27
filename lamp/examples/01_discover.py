# Поиск ламп в локальной сети (SSDP), аргументы не нужны.
from lamp.network import discover

for bulb in discover(timeout=2):
    print(bulb["ip"])
