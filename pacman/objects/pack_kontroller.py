from __future__ import annotations

from typing import Callable

from pygame.event import Event

from pacman.data_core import IEventful


class PackKontroller(IEventful):
    def __init__(self) -> None:
        self._players: dict[int, object] = {}
        self._player_factory: Callable[[], object] | None = None
        self._on_spawn: Callable[[int, object], None] | None = None
        self._on_remove: Callable[[int, object], None] | None = None

    def event_handler(self, event: Event) -> None:
        return

    def set_player_factory(self, factory: Callable[[], object]) -> None:
        self._player_factory = factory

    def set_spawn_listener(self, listener: Callable[[int, object], None]) -> None:
        self._on_spawn = listener

    def set_remove_listener(self, listener: Callable[[int, object], None]) -> None:
        self._on_remove = listener

    def bind_player(self, player_id: int, pacman_obj: object) -> None:
        self._players[player_id] = pacman_obj

    def unbind_player(self, player_id: int) -> object | None:
        return self._players.pop(player_id, None)

    def spawn(self, player_id: int, x: int, y: int) -> None:
        pacman = self._players.get(player_id)
        if pacman is None and self._player_factory is not None:
            pacman = self._player_factory()
            self.bind_player(player_id, pacman)
            if self._on_spawn is not None:
                self._on_spawn(player_id, pacman)
        if pacman is None:
            return
        pacman.teleport(x, y)
        pacman.go()

    def remove(self, player_id: int) -> None:
        pacman = self.unbind_player(player_id)
        if pacman is None:
            return
        pacman.stop()
        if self._on_remove is not None:
            self._on_remove(player_id, pacman)

    def up(self, player_id: int) -> None:
        self._move(player_id, "up")

    def right(self, player_id: int) -> None:
        self._move(player_id, "right")

    def left(self, player_id: int) -> None:
        self._move(player_id, "left")

    def down(self, player_id: int) -> None:
        self._move(player_id, "down")

    def stop(self, player_id: int) -> None:
        pacman = self._players.get(player_id)
        if pacman is None:
            return
        pacman.stop_move()

    def _move(self, player_id: int, direction: str) -> None:
        pacman = self._players.get(player_id)
        if pacman is None:
            return
        pacman.set_move_command(direction)
