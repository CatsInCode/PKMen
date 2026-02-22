from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pygame import KEYDOWN, K_1, K_2, K_3, K_4, K_5, K_6, K_7, K_8, K_DOWN, K_LEFT, K_RIGHT, K_UP
from pygame.event import Event

from pacman.data_core import IEventful


@dataclass
class _Command:
    action: str
    args: tuple


class PackKontroller(IEventful):
    """Command-style controller for Pacman players.

    Replace `commands` with your own ordered command list.
    Supported actions:
    - spawn(id, x, y)
    - remove(id)
    - up(id)
    - right(id)
    - left(id)
    - down(id)

    Demo bindings:
    - 1..8 run commands[0..7]
    - Arrow keys move player with id=1
    """

    def __init__(self) -> None:
        self._actions: dict[str, Callable] = {
            "spawn": self.spawn,
            "remove": self.remove,
            "up": self.up,
            "right": self.right,
            "left": self.left,
            "down": self.down,
        }
        self._players: dict[int, object] = {}
        self.commands: list[_Command] = [
            _Command("spawn", (1, 120, 200)),
            _Command("spawn", (2, 200, 200)),
            _Command("up", (1,)),
            _Command("right", (1,)),
            _Command("left", (2,)),
            _Command("down", (2,)),
            _Command("remove", (2,)),
        ]
        self._key_commands = {
            K_1: 0,
            K_2: 1,
            K_3: 2,
            K_4: 3,
            K_5: 4,
            K_6: 5,
            K_7: 6,
            K_8: 7,
        }

    def bind_player(self, player_id: int, pacman_obj: object) -> None:
        self._players[player_id] = pacman_obj

    def unbind_player(self, player_id: int) -> None:
        self._players.pop(player_id, None)

    def execute(self, action: str, *args) -> bool:
        command = self._actions.get(action)
        if command is None:
            return False
        command(*args)
        return True

    def run_command(self, idx: int) -> bool:
        if idx < 0 or idx >= len(self.commands):
            return False
        cmd = self.commands[idx]
        return self.execute(cmd.action, *cmd.args)

    def spawn(self, player_id: int, x: int, y: int) -> None:
        pacman = self._players.get(player_id)
        if not pacman:
            return
        pacman.teleport(x, y)
        pacman.go()

    def remove(self, player_id: int) -> None:
        pacman = self._players.get(player_id)
        if not pacman:
            return
        pacman.stop()
        self.unbind_player(player_id)

    def up(self, player_id: int) -> None:
        self._move(player_id, "up")

    def right(self, player_id: int) -> None:
        self._move(player_id, "right")

    def left(self, player_id: int) -> None:
        self._move(player_id, "left")

    def down(self, player_id: int) -> None:
        self._move(player_id, "down")

    def _move(self, player_id: int, direction: str) -> None:
        pacman = self._players.get(player_id)
        if not pacman:
            return
        pacman.set_move_command(direction)

    def event_handler(self, event: Event) -> None:
        if event.type != KEYDOWN:
            return
        cmd_idx = self._key_commands.get(event.key)
        if cmd_idx is not None:
            self.run_command(cmd_idx)
            return

        arrow_actions = {
            K_UP: self.up,
            K_RIGHT: self.right,
            K_LEFT: self.left,
            K_DOWN: self.down,
        }
        action = arrow_actions.get(event.key)
        if action is not None:
            action(1)
