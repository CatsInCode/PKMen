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
from pacman.misc.geometryCalculation import AnchorLayout, Point2D, PositionCells, UwbGeometryCalculator


# ===== module-level singletons =====
_MQTT_CTRL = None
_GEOM = None

# Режим парсинга входных сообщений:
# - "#triangulate": вход = дистанции до якорей (A1/A2/A3), дальше триангуляция
# - "#coordinates": вход =
#   - JSON в topic `uwb/tag/coordinates/<name>`: {"x":..., "y":...}
#   - либо раздельно: `uwb/tag/coordinates/<name>/x` и `/y` с числом в payload
INPUT_MODE = "#triangulate"


def _extract_coordinates(payload: dict, topic: str | None = None) -> PositionCells | None:
    def first_number(*keys):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, (int, float)):
                return int(round(value))
        return None

    x = first_number("x", "X", "cell_x", "cx")
    y = first_number("y", "Y", "cell_y", "cy")
    if x is None or y is None:
        return None

    # Имя игрока читаем из payload либо из topic: uwb/tag/coordinates/<name>
    topic_name = None
    if topic:
        prefix = "uwb/tag/coordinates/"
        if topic.startswith(prefix):
            topic_name = topic[len(prefix):] or None

    _name = payload.get("name") or payload.get("player") or topic_name
    _z = payload.get("z") or payload.get("Z")
    _ = (_name, _z)

    return PositionCells(x=x, y=y)


def _extract_coordinates_from_topic_value(topic: str, payload: dict, cache: dict[str, dict[str, int]]) -> PositionCells | None:
    prefix = "uwb/tag/coordinates/"
    if not topic.startswith(prefix):
        return None

    suffix = topic[len(prefix):].strip("/")
    if not suffix:
        return None

    parts = [p for p in suffix.split("/") if p]
    if not parts:
        return None

    name = parts[0]
    axis = parts[1].lower() if len(parts) > 1 else None

    if axis not in {"x", "y"}:
        return None

    value = payload.get("value")
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None

    if not isinstance(value, (int, float)):
        return None

    if name not in cache:
        cache[name] = {}

    cache[name][axis] = int(round(value))

    x = cache[name].get("x")
    y = cache[name].get("y")
    if x is None or y is None:
        return None

    return PositionCells(x=x, y=y)


def build_script(api):
    global _MQTT_CTRL, _GEOM

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
            topic_raw="uwb/tag/#",
            client_id=None,
        )
        _MQTT_CTRL.start()

    geom = _GEOM
    mqtt_ctrl = _MQTT_CTRL

    pac_id = 1
    api.spawn(pac_id, 1, 3)
    api.stop(pac_id)

    last_target_cell: tuple[int, int] | None = None
    last_send_ts = 0.0

    loop_dt = 0.05
    resend_same_target_sec = 0.25
    move_time_sec = 1
    target_visual_sec = 0.35
    dead_zone_cells = 1

    elapsed = 0.0
    coord_cache: dict[str, dict[str, int]] = {}

    def clamp_cell(x: int, y: int) -> tuple[int, int]:
        x = max(0, min(layout.map_w_cells - 1, x))
        y = max(0, min(layout.map_h_cells - 1, y))
        return x, y

    def is_likely_wall(x: int, y: int) -> bool:
        try:
            v = api.getBlockInfo(x, y)
            if isinstance(v, bool):
                return v
            return False
        except Exception:
            return False

    def find_reachable_candidate(x: int, y: int, max_r: int = 3) -> tuple[int, int]:
        x, y = clamp_cell(x, y)

        if not is_likely_wall(x, y):
            return x, y

        for r in range(1, max_r + 1):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    xx, yy = clamp_cell(x + dx, y + dy)
                    if not is_likely_wall(xx, yy):
                        return xx, yy

        return x, y

    while True:
        for line in mqtt_ctrl.drain_logs():
            print(line)

        for sample in mqtt_ctrl.drain_samples():
            payload = sample.payload
            mode = payload.get("mode", INPUT_MODE)
            if sample.topic.startswith("uwb/tag/coordinates"):
                mode = "#coordinates"
                prefix = "uwb/tag/coordinates/"
                if sample.topic.startswith(prefix):
                    topic_name = sample.topic[len(prefix):].split("/")[0].strip()
                    if topic_name and "name" not in payload:
                        payload["name"] = topic_name

            pos_c = None
            pos_m = None
            if mode == "#coordinates":
                pos_c = _extract_coordinates_from_topic_value(sample.topic, payload, coord_cache)
                if pos_c is None:
                    pos_c = _extract_coordinates(payload, sample.topic)
            else:
                res = geom.payload_to_cells(payload)
                if res is not None:
                    pos_m, pos_c = res

            if pos_c is not None:
                tx, ty = find_reachable_candidate(pos_c.x, pos_c.y, max_r=3)

                need_send = False
                if last_target_cell is None:
                    need_send = True
                else:
                    lx, ly = last_target_cell
                    if abs(tx - lx) > dead_zone_cells or abs(ty - ly) > dead_zone_cells:
                        need_send = True
                    elif elapsed - last_send_ts >= resend_same_target_sec:
                        need_send = True

                if need_send:
                    api.setTarget(tx + 1, ty + 1, target_visual_sec)
                    api.goToTime(pac_id, tx + 1, ty + 1, move_time_sec)

                    last_target_cell = (tx, ty)
                    last_send_ts = elapsed

                    if pos_m is not None:
                        print(
                            f"[UWB] meters=({pos_m.x:.2f},{pos_m.y:.2f}) "
                            f"-> cell=({pos_c.x},{pos_c.y}) -> cmd=({tx},{ty})"
                        )
                    else:
                        print(f"[UWB] coordinates mode -> cell=({pos_c.x},{pos_c.y}) -> cmd=({tx},{ty})")

        yield api.wait(loop_dt)
        elapsed += loop_dt
