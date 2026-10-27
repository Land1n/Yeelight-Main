# Цвет по RGB и по hex. Запуск: python 04_color.py <ip>
import sys

from lamp import Lamp, SetHexCommand, SetRgbCommand

bulb = Lamp(sys.argv[1])
SetRgbCommand(bulb, r=255, g=0, b=0).execute()
SetHexCommand(bulb, value="#33aaff").execute()
print(bulb.state()["rgb"])
