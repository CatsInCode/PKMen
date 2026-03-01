from __future__ import annotations

# Edit only this function.
# Commands available:
## x/y are map cell coordinates
# api.spawn(id, x, y)
# api.remove(id)
# api.up(id) / api.right(id) / api.left(id) / api.down(id) / api.stop(id)
# api.goTo(id, x, y) / api.goToTime(id, x, y, time_sec)
# api.setTarget(x, y, time_sec)
# api.getBlockInfo(x, y) -> bool
# yield api.wait(seconds)
# yield api.wait_key("u")

from pacman.objects.mqttController import MqttUwbController
from pacman.misc.geometryCalculation import AnchorLayout, Point2D, UwbGeometryCalculator


# ===== module-level singletons =====
_MQTT_CTRL = None
_GEOM = None


def build_script(api):
    global _MQTT_CTRL, _GEOM

    # === Подгони под твой эмулятор UWB ===
    layout = AnchorLayout(
        A1=Point2D(0.5, 0.5),
        A2=Point2D(9.5, 0.5),
        A3=Point2D(5.0, 5.5),
        world_w_m=10.0,
        world_h_m=6.0,
        map_w_cells=28,
        map_h_cells=31,
    )

    if _GEOM is None:
        _GEOM = UwbGeometryCalculator(layout, ema_alpha=0.35)

    if _MQTT_CTRL is None:
        _MQTT_CTRL = MqttUwbController(
            host="192.168.0.110",
            port=1883,
            topic_raw="uwb/tag/raw",
            client_id=None,  # уникальный
        )
        _MQTT_CTRL.start()

    geom = _GEOM
    mqtt_ctrl = _MQTT_CTRL

    pac_id = 1
    api.spawn(pac_id, 1, 3)
    api.stop(pac_id)

    # Последняя отправленная цель
    last_target_cell: tuple[int, int] | None = None
    last_send_ts = 0.0

    # Параметры поведения (подкрутил для "видимого" движения)
    loop_dt = 0.05
    resend_same_target_sec = 0.25
    move_time_sec = 1       # было 0.12 -> часто слишком резко/часто
    target_visual_sec = 0.35
    dead_zone_cells = 1        # если цель изменилась меньше чем на 1 клетку — не дёргаем

    elapsed = 0.0

    def clamp_cell(x: int, y: int) -> tuple[int, int]:
        x = max(0, min(layout.map_w_cells - 1, x))
        y = max(0, min(layout.map_h_cells - 1, y))
        return x, y

    def is_likely_wall(x: int, y: int) -> bool:
        """
        У api.getBlockInfo() семантика может отличаться.
        Поэтому:
        - если упадет/непонятно -> считаем НЕ стеной
        - используем только как эвристику
        """
        try:
            v = api.getBlockInfo(x, y)
            # Попробуем обе трактовки через тип:
            # если bool -> чаще всего True = стена, но это не гарантировано
            if isinstance(v, bool):
                return v
            # если что-то иное (int/obj) — не считаем стеной
            return False
        except Exception:
            return False

    def find_reachable_candidate(x: int, y: int, max_r: int = 3) -> tuple[int, int]:
        """
        Берём цель как есть.
        Если вдруг это стена — ищем рядом.
        Даже если getBlockInfo трактуется не так, это не ломает движение полностью.
        """
        x, y = clamp_cell(x, y)

        # Сначала пробуем напрямую
        if not is_likely_wall(x, y):
            return x, y

        # Поиск вокруг
        for r in range(1, max_r + 1):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    xx, yy = clamp_cell(x + dx, y + dy)
                    if not is_likely_wall(xx, yy):
                        return xx, yy

        # fallback: всё равно вернуть исходную
        return x, y

    while True:
        for line in mqtt_ctrl.drain_logs():
            print(line)

        sample = mqtt_ctrl.get_latest_sample()
        if sample is not None:
            res = geom.payload_to_cells(sample.payload)
            if res is not None:
                pos_m, pos_c = res

                tx, ty = find_reachable_candidate(pos_c.x, pos_c.y, max_r=3)

                need_send = False
                if last_target_cell is None:
                    need_send = True
                else:
                    lx, ly = last_target_cell
                    # Dead-zone по клеткам
                    if abs(tx - lx) > dead_zone_cells or abs(ty - ly) > dead_zone_cells:
                        need_send = True
                    elif elapsed - last_send_ts >= resend_same_target_sec:
                        need_send = True

                if need_send:
                    # Подсветка цели (если движок её показывает)
                    api.setTarget(tx+1, ty+1, target_visual_sec)

                    # Главное движение
                    print(tx, ty)
                    api.goToTime(pac_id, tx+1, ty+1, move_time_sec)

                    last_target_cell = (tx, ty)
                    last_send_ts = elapsed

                    print(
                        f"[UWB] meters=({pos_m.x:.2f},{pos_m.y:.2f}) "
                        f"-> cell=({pos_c.x},{pos_c.y}) -> cmd=({tx},{ty})"
                    )

        yield api.wait(loop_dt)
        elapsed += loop_dt
