# Яркость от 1 до 100. Запуск: python 03_brightness.py <ip>
import sys

from lamp import Lamp, SetBrightnessCommand

bulb = Lamp(sys.argv[1])
SetBrightnessCommand(bulb, value=30).execute()
print(bulb.state()["bright"])
