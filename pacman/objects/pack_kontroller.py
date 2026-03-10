from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from pygame import Color, draw
from pygame.surface import Surface
from typing import Callable

from pygame.event import Event

from pacman.data_core import Cfg, IEventful
from pacman.misc import CellUtil


@dataclass
class _TargetMark:
    cell_x: int
    cell_y: int
    left_time: float
    color: str = "red"


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
        self._request_targets: dict[int, tuple[int, int]] = {}
        self._targets: list[_TargetMark] = []
        self._targets_visible = True

    def event_handler(self, event: Event) -> None:
        return

    def update(self, dt_seconds: float = 1 / Cfg.FPS) -> None:
        for player_id in list(self._routes.keys()):
            self._update_route(player_id)

        if dt_seconds <= 0:
            return
        for target in self._targets:
            target.left_time -= dt_seconds
        self._targets = [target for target in self._targets if target.left_time > 0]

    def draw_targets(self, screen: Surface) -> None:
        if not self._targets_visible:
            return

        for cell_x, cell_y in self._request_targets.values():
            cx, cy = CellUtil.get_center_pos((cell_x, cell_y))
            draw.circle(screen, Color("red"), (cx, cy), Cfg.TILE_SIZE // 3)

        for target in self._targets:
            cx, cy = CellUtil.get_center_pos((target.cell_x, target.cell_y))
            draw.circle(screen, Color(target.color), (cx, cy), Cfg.TILE_SIZE // 3)

    def setTarget(self, cell_x: int, cell_y: int, time_sec: float, color: str = "red") -> bool:
        if time_sec <= 0:
            return False
        try:
            Color(color)
        except ValueError:
            color = "red"
        self._targets.append(_TargetMark(cell_x, cell_y, float(time_sec), color=color))
        return True


    def set_targets_visible(self, enabled: bool) -> None:
        self._targets_visible = bool(enabled)

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
        self._request_targets.pop(player_id, None)
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

    def getBlockInfo(self, cell_x: int, cell_y: int) -> bool:
        pacman = next(iter(self._players.values()), None)
        if pacman is None:
            return False
        collision_map = pacman.level_loader.collision_map
        if not collision_map:
            return False
        rows = len(collision_map)
        cols = len(collision_map[0])
        if not (0 <= cell_x < cols and 0 <= cell_y < rows):
            return False
        return collision_map[cell_y][cell_x] != 0

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
        requested_target = (target_x, target_y)
        self._request_targets[player_id] = requested_target

        target = self._resolve_target_cell(pacman, start, requested_target)
        if target is None:
            return False
        if target != requested_target:
            self.setTarget(target[0], target[1], 1.2, color="green")

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
            speed = max(1.0, distance_px / (time_sec * Cfg.FPS))

        pacman.set_move_speed(speed)
        self._routes[player_id] = _RouteState(path, speed)
        self._apply_next_direction(player_id)
        return True

    def _resolve_target_cell(
        self,
        pacman,
        start: tuple[int, int],
        requested_target: tuple[int, int],
    ) -> tuple[int, int] | None:
        tx, ty = requested_target
        if self._is_valid_target_cell(pacman, tx, ty):
            return requested_target

        direction = self._get_player_move_direction(pacman)
        if direction is None:
            return None

        sx, sy = start
        on_motion_line = ((direction in {"left", "right"} and ty == sy) or
                          (direction in {"up", "down"} and tx == sx))

        if on_motion_line:
            return self._resolve_target_on_motion_line(pacman, start, requested_target, direction)

        return self._resolve_target_on_perpendicular_ray(pacman, start, requested_target, direction)

    def _resolve_target_on_motion_line(
        self,
        pacman,
        start: tuple[int, int],
        requested_target: tuple[int, int],
        direction: str,
    ) -> tuple[int, int] | None:
        sx, sy = start
        tx, ty = requested_target

        if direction in {"left", "right"}:
            step_x = 1 if sx > tx else -1 if sx < tx else 0
            if step_x == 0:
                return None
            x = tx
            while x != sx:
                x += step_x
                if not self._is_in_bounds(pacman, x, ty):
                    return None
                if self._is_valid_target_cell(pacman, x, ty):
                    return x, ty
            return None

        step_y = 1 if sy > ty else -1 if sy < ty else 0
        if step_y == 0:
            return None
        y = ty
        while y != sy:
            y += step_y
            if not self._is_in_bounds(pacman, tx, y):
                return None
            if self._is_valid_target_cell(pacman, tx, y):
                return tx, y
        return None

    def _resolve_target_on_perpendicular_ray(
        self,
        pacman,
        start: tuple[int, int],
        requested_target: tuple[int, int],
        direction: str,
    ) -> tuple[int, int] | None:
        sx, sy = start
        tx, ty = requested_target

        step_x, step_y = 0, 0
        if direction in {"left", "right"}:
            if sy == ty:
                return None
            step_y = -1 if sy < ty else 1
        else:
            if sx == tx:
                return None
            step_x = -1 if sx < tx else 1

        for step in range(1, 4):
            x = tx + step_x * step
            y = ty + step_y * step
            if not self._is_in_bounds(pacman, x, y):
                return None
            if self._is_valid_target_cell(pacman, x, y):
                return x, y
        return None

    def _get_player_move_direction(self, pacman) -> str | None:
        direction = {
            (1, 0): "right",
            (-1, 0): "left",
            (0, 1): "down",
            (0, -1): "up",
        }
        shift = (getattr(pacman, "shift_x", 0), getattr(pacman, "shift_y", 0))
        return direction.get(shift)

    def _is_valid_target_cell(self, pacman, cell_x: int, cell_y: int) -> bool:
        if not self._is_in_bounds(pacman, cell_x, cell_y):
            return False
        collision_map = pacman.level_loader.collision_map
        return collision_map[cell_y][cell_x] != 0

    def _is_in_bounds(self, pacman, cell_x: int, cell_y: int) -> bool:
        collision_map = pacman.level_loader.collision_map
        rows = len(collision_map)
        cols = len(collision_map[0]) if rows else 0
        return 0 <= cell_x < cols and 0 <= cell_y < rows

    def _update_route(self, player_id: int) -> None:
        pacman = self._players.get(player_id)
        route = self._routes.get(player_id)
        if pacman is None or route is None:
            return

        target_cell = route.cells[-1]
        current_cell = pacman.get_cell()

        # 1) Самый жёсткий и надёжный кейс:
        # если уже оказались в целевой клетке, сразу защёлкиваем в её центр и завершаем маршрут.
        if current_cell == target_cell:
            target_cx, target_cy = CellUtil.get_center_pos(target_cell)
            pacman.teleport(target_cx, target_cy)
            pacman.stop_move()
            self._routes.pop(player_id, None)
            return

        # Направление меняем только в центре клетки.
        if not CellUtil.is_in_cell_center(pacman.rect):
            return

        self._apply_next_direction(player_id)

    def _apply_next_direction(self, player_id: int) -> None:
        pacman = self._players.get(player_id)
        route = self._routes.get(player_id)
        if pacman is None or route is None:
            return

        current = pacman.get_cell()
        target = route.cells[-1]

        if current == target:
            target_cx, target_cy = CellUtil.get_center_pos(target)
            pacman.teleport(target_cx, target_cy)
            pacman.stop_move()
            self._routes.pop(player_id, None)
            return

        try:
            idx = route.cells.index(current)
        except ValueError:
            if not self._rebuild_route_from_current(player_id, route.speed):
                pacman.stop_move()
                self._routes.pop(player_id, None)
            return

        if idx >= len(route.cells) - 1:
            target_cx, target_cy = CellUtil.get_center_pos(target)
            pacman.teleport(target_cx, target_cy)
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
            if not self._rebuild_route_from_current(player_id, route.speed):
                pacman.stop_move()
                self._routes.pop(player_id, None)
            return

        pacman.set_move_speed(route.speed)
        pacman.set_move_command(direction)

    def _rebuild_route_from_current(self, player_id: int, speed: float) -> bool:
        pacman = self._players.get(player_id)
        route = self._routes.get(player_id)
        if pacman is None or route is None:
            return False

        start = pacman.get_cell()
        target = route.cells[-1]
        rebuilt_path = self._build_path(pacman, start, target)
        if len(rebuilt_path) <= 1:
            return False

        self._routes[player_id] = _RouteState(rebuilt_path, speed)
        self._apply_next_direction(player_id)
        return True

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
