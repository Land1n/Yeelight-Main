# Включить и выключить лампу. Запуск: python 02_turn_on_off.py <ip>
import sys

from lamp import Lamp, TurnOffCommand, TurnOnCommand

bulb = Lamp(sys.argv[1])
TurnOnCommand(bulb).execute()
print(bulb.state()["power"])
TurnOffCommand(bulb).execute()
print(bulb.state()["power"])
