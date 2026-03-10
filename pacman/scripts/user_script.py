from __future__ import annotations

# Edit only this function.
# Commands available:
## x/y are map cell coordinates
# api.spawn(id, x, y)
# api.remove(id)
# api.up(id) / api.right(id) / api.left(id) / api.down(id) / api.stop(id)
# api.goTo(id, x, y) / api.goToTime(id, x, y, time_sec)
# api.setTarget(x, y, time_sec, color="red")
# api.getBlockInfo(x, y) -> bool
# yield api.wait(seconds)
# yield api.wait_key("u")

from pacman.objects.mqttController import MqttUwbController
from pacman.misc.geometryCalculation import AnchorLayout, Point2D, PositionCells, UwbGeometryCalculator
from pacman.control_panel import control_panel


# ===== module-level singletons =====
_MQTT_CTRL = None
_GEOM = None

# Режим парсинга входных сообщений:
# - "#triangulate": вход = дистанции до якорей (A1/A2/A3), дальше триангуляция
# - "#coordinates": вход только из topic `uwb/tag/coordinate/<name>/x|y|z`
#   где движение считается по x/y (z логируется, но не влияет на 2D)
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
            topic_name = topic[len(prefix):].split("/")[0].strip() or None

    _name = payload.get("name") or payload.get("player") or topic_name
    _ = _name

    return PositionCells(x=x, y=y)


def _extract_coordinates_from_topic_value(topic: str, payload: dict, cache: dict[str, dict[str, int]]) -> PositionCells | None:
    # Strict supported format (as requested):
    # - uwb/tag/coordinate/<name>/x|y|z
    prefix = "uwb/tag/coordinate/"
    if not topic.startswith(prefix):
        return None

    suffix = topic[len(prefix):].strip("/")
    parts = [p for p in suffix.split("/") if p]
    if len(parts) != 2:
        return None

    name, axis = parts[0], parts[1].lower()
    if axis not in {"x", "y", "z"}:
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

    # 2D: keep z for debug only, movement uses x/y only
    cache[name][axis] = int(round(value))

    x = cache[name].get("x")
    y = cache[name].get("y")
    if x is None or y is None:
        return None

    return PositionCells(x=x, y=y)


def _extract_player_name(payload: dict, topic: str) -> str | None:
    name = payload.get("name") or payload.get("player")
    if isinstance(name, str) and name.strip():
        return name.strip()

    prefix = "uwb/tag/coordinate/"
    if topic.startswith(prefix):
        parts = [p for p in topic[len(prefix):].split("/") if p]
        if len(parts) >= 1:
            return parts[0].strip() or None

    return None


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

    player_ids: dict[str, int] = {}
    next_player_id = 1

    last_target_cell_by_player: dict[str, tuple[int, int] | None] = {}
    last_send_ts_by_player: dict[str, float] = {}
    last_input_cell_by_player: dict[str, tuple[int, int] | None] = {}
    blocked_players: set[str] = set()

    loop_dt = 0.05
    dead_zone_cells = 1

    elapsed = 0.0
    coord_cache: dict[str, dict[str, int]] = {}

    def clamp_cell(x: int, y: int) -> tuple[int, int]:
        x = max(0, min(layout.map_w_cells - 1, x))
        y = max(0, min(layout.map_h_cells - 1, y))
        return x, y

    while True:
        mqtt_ctrl.drain_logs()
        invert_x = control_panel.is_mqtt_invert_x_enabled()
        invert_y = control_panel.is_mqtt_invert_y_enabled()

        for kicked_name in control_panel.drain_kick_players():
            blocked_players.add(kicked_name)
            kicked_id = player_ids.pop(kicked_name, None)
            if kicked_id is not None:
                api.remove(kicked_id)
            last_target_cell_by_player.pop(kicked_name, None)
            last_send_ts_by_player.pop(kicked_name, None)
            last_input_cell_by_player.pop(kicked_name, None)
            coord_cache.pop(kicked_name, None)

        for sample in mqtt_ctrl.drain_samples():
            payload = sample.payload
            mode = payload.get("mode", INPUT_MODE)
            player_name = _extract_player_name(payload, sample.topic) or "default"

            topic_parts = [p for p in sample.topic.split("/") if p]
            is_axis_topic = len(topic_parts) >= 3 and topic_parts[-1] in {"x", "y", "z"}
            if sample.topic.startswith("uwb/tag/coordinate/") and is_axis_topic:
                mode = "#coordinates"
                player_name = _extract_player_name(payload, sample.topic) or player_name
                if player_name and "name" not in payload:
                    payload["name"] = player_name

            pos_c = None
            pos_m = None
            if mode == "#coordinates":
                pos_c = _extract_coordinates_from_topic_value(sample.topic, payload, coord_cache)

                if pos_c is None:
                    pass
            else:
                res = geom.payload_to_cells(payload)
                if res is not None:
                    pos_m, pos_c = res

            if pos_c is not None:
                player_name = _extract_player_name(payload, sample.topic) or "default"
                if player_name in blocked_players:
                    continue

                last_input_cell_by_player[player_name] = (pos_c.x, pos_c.y)

                if player_name not in player_ids:
                    player_ids[player_name] = next_player_id
                    api.spawn(next_player_id, 1, 3)
                    api.stop(next_player_id)
                    last_target_cell_by_player[player_name] = None
                    last_send_ts_by_player[player_name] = 0.0
                    print(f"Find pacman: {player_name}")
                    print(f"Command: summon - {player_name}")
                    next_player_id += 1

                pac_id = player_ids[player_name]
                raw_x, raw_y = pos_c.x, pos_c.y
                if invert_x:
                    raw_x = 28 - raw_x
                if invert_y:
                    raw_y = 30 - raw_y
                requested_tx, requested_ty = clamp_cell(raw_x, raw_y)

                last_target_cell = last_target_cell_by_player.get(player_name)
                need_send = False
                if last_target_cell is None:
                    need_send = True
                else:
                    lx, ly = last_target_cell

                    # Новую команду шлём только если цель реально сменилась заметно.
                    if abs(requested_tx - lx) > dead_zone_cells or abs(requested_ty - ly) > dead_zone_cells:
                        need_send = True

                if need_send:
                    sent = api.goTo(pac_id, requested_tx, requested_ty)

                    if sent:
                        last_target_cell_by_player[player_name] = (requested_tx, requested_ty)
                        last_send_ts_by_player[player_name] = elapsed
                        print(f"Command: moveTo - {player_name}")
                    else:
                        # Не дёргаем игрока лишним stop на каждом плохом пакете,
                        # просто не обновляем target.
                        pass

        control_panel.set_active_players([name for name in player_ids.keys() if name not in blocked_players])

        yield api.wait(loop_dt)
        elapsed += loop_dt
