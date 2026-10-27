# Включить LAN Control. Запуск: python 09_lan_control.py <ip> [token]
import sys

from lamp.network import enable_lan_control

token = sys.argv[2] if len(sys.argv) > 2 else None
print(enable_lan_control(sys.argv[1], token))
