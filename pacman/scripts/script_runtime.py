from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generator, Optional, Set


@dataclass
class WaitSeconds:
    seconds: float


@dataclass
class WaitKey:
    key_name: str


class ScriptAPI:
    def __init__(self, pack_controller, pressed_keys: Set[str]):
        self._controller = pack_controller
        self._pressed_keys = pressed_keys

    def spawn(self, player_id: int, x: int, y: int) -> None:
        self._controller.spawn(player_id, x, y)

    def remove(self, player_id: int) -> None:
        self._controller.remove(player_id)

    def up(self, player_id: int) -> None:
        self._controller.up(player_id)

    def down(self, player_id: int) -> None:
        self._controller.down(player_id)

    def left(self, player_id: int) -> None:
        self._controller.left(player_id)

    def right(self, player_id: int) -> None:
        self._controller.right(player_id)

    def stop(self, player_id: int) -> None:
        self._controller.stop(player_id)

    def goTo(self, player_id: int, cell_x: int, cell_y: int) -> bool:
        return self._controller.goTo(player_id, cell_x, cell_y)

    def goToTime(self, player_id: int, cell_x: int, cell_y: int, time_sec: float) -> bool:
        return self._controller.goToTime(player_id, cell_x, cell_y, time_sec)

    def setTarget(self, cell_x: int, cell_y: int, time_sec: float) -> bool:
        return self._controller.setTarget(cell_x, cell_y, time_sec)

    def getBlockInfo(self, cell_x: int, cell_y: int) -> bool:
        return self._controller.getBlockInfo(cell_x, cell_y)

    def wait(self, seconds: float) -> WaitSeconds:
        return WaitSeconds(seconds)

    def wait_key(self, key_name: str) -> WaitKey:
        return WaitKey(key_name.lower())

    def is_key_pressed(self, key_name: str) -> bool:
        return key_name.lower() in self._pressed_keys


class ScriptRunner:
    def __init__(self, script_factory: Callable[[ScriptAPI], Generator[Any, None, None]], api: ScriptAPI):
        self._script_factory = script_factory
        self._api = api
        self._generator: Optional[Generator[Any, None, None]] = None
        self._wait_timer = 0.0
        self._wait_key: Optional[str] = None

    def start(self) -> None:
        self._generator = self._script_factory(self._api)
        self._wait_timer = 0.0
        self._wait_key = None
        self._advance_script()

    def restart(self) -> None:
        self.start()

    def update(self, dt_seconds: float) -> None:
        if self._generator is None:
            return

        if self._wait_timer > 0:
            self._wait_timer -= dt_seconds
            if self._wait_timer > 0:
                return
            self._wait_timer = 0.0
            self._advance_script()
            return

        if self._wait_key is not None:
            if self._api.is_key_pressed(self._wait_key):
                self._wait_key = None
                self._advance_script()
            return

        self._advance_script()

    def _advance_script(self) -> None:
        if self._generator is None:
            return

        while True:
            try:
                token = next(self._generator)
            except StopIteration:
                self.restart()
                return

            if isinstance(token, WaitSeconds):
                self._wait_timer = max(0.0, float(token.seconds))
                return

            if isinstance(token, WaitKey):
                self._wait_key = token.key_name.lower()
                return
