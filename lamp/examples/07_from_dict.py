# Команда из словаря, так её присылает manager. Запуск: python 07_from_dict.py <ip>
import sys

from lamp import Command

cmd = Command.from_dict({"type": "set_rgb", "ip": sys.argv[1], "r": 255, "g": 0, "b": 0})
cmd.execute()
cmd.undo()
print(cmd.to_dict())
