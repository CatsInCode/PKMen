from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class Point2D:
    x: float
    y: float


@dataclass
class AnchorLayout:
    # Координаты якорей в МЕТРАХ (должны совпадать с браузерным эмулятором)
    A1: Point2D
    A2: Point2D
    A3: Point2D

    # Размер "зоны" в метрах (что рисуешь в браузерном эмуляторе)
    world_w_m: float
    world_h_m: float

    # Размер карты в клетках PKMen2 (x: 0..27, y: 0..30 для твоей карты 28x31)
    map_w_cells: int
    map_h_cells: int


@dataclass
class PositionMeters:
    x: float
    y: float


@dataclass
class PositionCells:
    x: int
    y: int


class UwbGeometryCalculator:
    """
    Считает координаты тега по трем расстояниям (2D trilateration),
    затем переводит метры в клетки карты.
    """
    def __init__(self, layout: AnchorLayout, ema_alpha: float = 0.35):
        self.layout = layout
        self.ema_alpha = max(0.01, min(1.0, ema_alpha))
        self._smooth_xy: Optional[PositionMeters] = None

    @staticmethod
    def _distance_from_payload(anchor_payload: dict) -> Optional[float]:
        # Предпочитаем filtered distance, fallback -> raw
        for key in ("distance", "raw"):
            v = anchor_payload.get(key)
            if isinstance(v, (int, float)):
                return float(v)
        return None

    def parse_distances(self, payload: dict) -> Optional[tuple[float, float, float]]:
        try:
            d1 = self._distance_from_payload(payload["A1"])
            d2 = self._distance_from_payload(payload["A2"])
            d3 = self._distance_from_payload(payload["A3"])
            if d1 is None or d2 is None or d3 is None:
                return None
            return d1, d2, d3
        except Exception:
            return None

    def trilaterate_2d(self, d1: float, d2: float, d3: float) -> Optional[PositionMeters]:
        """
        Линейная 2D триангуляция по трем окружностям:
        вычитаем уравнение A1 из A2 и A3 -> система 2x2.
        """
        p1 = self.layout.A1
        p2 = self.layout.A2
        p3 = self.layout.A3

        # A*x + B*y = C
        A = 2.0 * (p2.x - p1.x)
        B = 2.0 * (p2.y - p1.y)
        C = (d1 * d1 - d2 * d2) - (p1.x * p1.x + p1.y * p1.y) + (p2.x * p2.x + p2.y * p2.y)

        D = 2.0 * (p3.x - p1.x)
        E = 2.0 * (p3.y - p1.y)
        F = (d1 * d1 - d3 * d3) - (p1.x * p1.x + p1.y * p1.y) + (p3.x * p3.x + p3.y * p3.y)

        det = A * E - B * D
        if abs(det) < 1e-9:
            return None  # вырожденная геометрия (якоря почти на одной линии и т.п.)

        x = (C * E - B * F) / det
        y = (A * F - C * D) / det

        # clamp в пределах зоны (эмулятор у тебя работает в прямоугольнике)
        x = max(0.0, min(self.layout.world_w_m, x))
        y = max(0.0, min(self.layout.world_h_m, y))

        pos = PositionMeters(x=x, y=y)
        return self._smooth(pos)

    def _smooth(self, pos: PositionMeters) -> PositionMeters:
        if self._smooth_xy is None:
            self._smooth_xy = pos
            return pos

        a = self.ema_alpha
        sx = a * pos.x + (1 - a) * self._smooth_xy.x
        sy = a * pos.y + (1 - a) * self._smooth_xy.y
        self._smooth_xy = PositionMeters(sx, sy)
        return self._smooth_xy

    def meters_to_cells(self, pos_m: PositionMeters) -> PositionCells:
        # Перевод "метры внутри зоны" -> "клетки карты"
        # 0..world_w -> 0..(map_w_cells-1)
        # 0..world_h -> 0..(map_h_cells-1)
        if self.layout.world_w_m <= 0 or self.layout.world_h_m <= 0:
            return PositionCells(0, 0)

        x_norm = pos_m.x / self.layout.world_w_m
        y_norm = pos_m.y / self.layout.world_h_m

        x = int(round(x_norm * (self.layout.map_w_cells - 1)))
        y = int(round(y_norm * (self.layout.map_h_cells - 1)))

        x = max(0, min(self.layout.map_w_cells - 1, x))
        y = max(0, min(self.layout.map_h_cells - 1, y))
        return PositionCells(x=x, y=y)

    def payload_to_cells(self, payload: dict) -> Optional[tuple[PositionMeters, PositionCells]]:
        ds = self.parse_distances(payload)
        if ds is None:
            return None
        d1, d2, d3 = ds

        pos_m = self.trilaterate_2d(d1, d2, d3)
        if pos_m is None:
            return None

        pos_c = self.meters_to_cells(pos_m)
        return pos_m, pos_c
