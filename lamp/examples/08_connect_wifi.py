# Настройка Wi-Fi ненастроенной лампы (режим точки доступа). Запуск: python 08_connect_wifi.py <ip> <ssid>
import getpass
import sys

from lamp.network import connect_to_wifi

password = getpass.getpass("Пароль Wi-Fi: ")
print(connect_to_wifi(sys.argv[1], sys.argv[2], password, enable_lan_control=True))
