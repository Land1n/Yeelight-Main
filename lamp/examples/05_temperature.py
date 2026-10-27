# Цветовая температура от 1700 до 6500 K. Запуск: python 05_temperature.py <ip>
import sys

from lamp import Lamp, SetColorTempCommand

bulb = Lamp(sys.argv[1])
SetColorTempCommand(bulb, kelvin=4000).execute()
print(bulb.state()["ct"])
