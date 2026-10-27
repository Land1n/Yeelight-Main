# Откат: undo возвращает состояние, снятое перед execute. Запуск: python 06_commands_and_undo.py <ip>
import sys

from lamp import Lamp, SetBrightnessCommand

bulb = Lamp(sys.argv[1])
cmd = SetBrightnessCommand(bulb, value=10)
cmd.execute()
cmd.undo()
print(bulb.state()["bright"])
