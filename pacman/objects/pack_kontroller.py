from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable

from pygame.event import Event

from pacman.data_core import Cfg, IEventful
from pacman.misc import CellUtil


@dataclass
class _RouteState:
    cells: list[tuple[int, int]]
    speed: float


class PackKontroller(IEventful):
    _DIRS = ((1, 0, "right", 0), (0, 1, "down", 1), (-1, 0, "left", 2), (0, -1, "up", 3))

    def __init__(self) -> None:
        self._players: dict[int, object] = {}
        self._player_factory: Callable[[], object] | None = None
        self._on_spawn: Callable[[int, object], None] | None = None
        self._on_remove: Callable[[int, object], None] | None = None
        self._routes: dict[int, _RouteState] = {}

    def event_handler(self, event: Event) -> None:
        return

    def update(self) -> None:
        for player_id in list(self._routes.keys()):
            self._update_route(player_id)

    def set_player_factory(self, factory: Callable[[], object]) -> None:
        self._player_factory = factory

    def set_spawn_listener(self, listener: Callable[[int, object], None]) -> None:
        self._on_spawn = listener

    def set_remove_listener(self, listener: Callable[[int, object], None]) -> None:
        self._on_remove = listener

    def bind_player(self, player_id: int, pacman_obj: object) -> None:
        self._players[player_id] = pacman_obj

    def unbind_player(self, player_id: int) -> object | None:
        self._routes.pop(player_id, None)
        return self._players.pop(player_id, None)

    def spawn(self, player_id: int, cell_x: int, cell_y: int) -> None:
        pacman = self._players.get(player_id)
        if pacman is None and self._player_factory is not None:
            pacman = self._player_factory()
            self.bind_player(player_id, pacman)
            if self._on_spawn is not None:
                self._on_spawn(player_id, pacman)
        if pacman is None:
            return
        self._routes.pop(player_id, None)
        pacman.teleport(*CellUtil.get_center_pos((cell_x, cell_y)))
        pacman.stop_move()

    def remove(self, player_id: int) -> None:
        pacman = self.unbind_player(player_id)
        if pacman is None:
            return
        pacman.stop_move()
        if self._on_remove is not None:
            self._on_remove(player_id, pacman)

    def up(self, player_id: int) -> None:
        self._routes.pop(player_id, None)
        self._move(player_id, "up")

    def right(self, player_id: int) -> None:
        self._routes.pop(player_id, None)
        self._move(player_id, "right")

    def left(self, player_id: int) -> None:
        self._routes.pop(player_id, None)
        self._move(player_id, "left")

    def down(self, player_id: int) -> None:
        self._routes.pop(player_id, None)
        self._move(player_id, "down")

    def stop(self, player_id: int) -> None:
        self._routes.pop(player_id, None)
        pacman = self._players.get(player_id)
        if pacman is None:
            return
        pacman.stop_move()

    def goTo(self, player_id: int, cell_x: int, cell_y: int) -> bool:
        return self._start_route(player_id, cell_x, cell_y, None)

    def goToTime(self, player_id: int, cell_x: int, cell_y: int, time_sec: float) -> bool:
        if time_sec <= 0:
            return False
        return self._start_route(player_id, cell_x, cell_y, time_sec)

    def _start_route(self, player_id: int, target_x: int, target_y: int, time_sec: float | None) -> bool:
        pacman = self._players.get(player_id)
        if pacman is None:
            return False

        start = pacman.get_cell()
        target = (target_x, target_y)
        path = self._build_path(pacman, start, target)
        if not path:
            return False
        if len(path) == 1:
            pacman.stop_move()
            return True

        speed = 1.0
        if time_sec is not None:
            steps = len(path) - 1
            distance_px = steps * Cfg.TILE_SIZE
            speed = max(0.1, distance_px / (time_sec * Cfg.FPS))

        pacman.set_move_speed(speed)
        self._routes[player_id] = _RouteState(path, speed)
        self._apply_next_direction(player_id)
        return True

    def _update_route(self, player_id: int) -> None:
        pacman = self._players.get(player_id)
        route = self._routes.get(player_id)
        if pacman is None or route is None:
            return

        if not CellUtil.is_in_cell_center(pacman.rect):
            return

        current_cell = pacman.get_cell()
        if current_cell == route.cells[-1]:
            pacman.stop_move()
            self._routes.pop(player_id, None)
            return

        self._apply_next_direction(player_id)

    def _apply_next_direction(self, player_id: int) -> None:
        pacman = self._players.get(player_id)
        route = self._routes.get(player_id)
        if pacman is None or route is None:
            return

        current = pacman.get_cell()
        if current not in route.cells:
            pacman.stop_move()
            self._routes.pop(player_id, None)
            return

        idx = route.cells.index(current)
        if idx >= len(route.cells) - 1:
            pacman.stop_move()
            self._routes.pop(player_id, None)
            return

        nxt = route.cells[idx + 1]
        dx = nxt[0] - current[0]
        dy = nxt[1] - current[1]
        if dx > 1:
            dx = -1
        elif dx < -1:
            dx = 1
        if dy > 1:
            dy = -1
        elif dy < -1:
            dy = 1

        direction = {
            (1, 0): "right",
            (-1, 0): "left",
            (0, 1): "down",
            (0, -1): "up",
        }.get((dx, dy))
        if direction is None:
            pacman.stop_move()
            self._routes.pop(player_id, None)
            return

        pacman.set_move_speed(route.speed)
        pacman.set_move_command(direction)

    def _build_path(self, pacman, start: tuple[int, int], target: tuple[int, int]) -> list[tuple[int, int]]:
        collision_map = pacman.level_loader.collision_map
        rows = len(collision_map)
        cols = len(collision_map[0])

        if not (0 <= target[0] < cols and 0 <= target[1] < rows):
            return []

        queue = deque([start])
        prev: dict[tuple[int, int], tuple[int, int] | None] = {start: None}

        while queue:
            cell = queue.popleft()
            if cell == target:
                break

            moves = pacman.movement_cell(cell)
            for dx, dy, _name, move_idx in self._DIRS:
                if not moves[move_idx]:
                    continue
                nx = (cell[0] + dx) % cols
                ny = (cell[1] + dy) % rows
                ncell = (nx, ny)
                if ncell in prev:
                    continue
                prev[ncell] = cell
                queue.append(ncell)

        if target not in prev:
            return []

        path = []
        cur = target
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        path.reverse()
        return path

    def _move(self, player_id: int, direction: str) -> None:
        pacman = self._players.get(player_id)
        if pacman is None:
            return
        pacman.set_move_speed(1.0)
        pacman.set_move_command(direction)
