from __future__ import annotations

from collections import deque

# Edit only this function.
# Commands available:
## x/y are map cell coordinates
# api.spawn(id, x, y)
# api.remove(id)
# api.up(id) / api.right(id) / api.left(id) / api.down(id) / api.stop(id)
# api.goTo(id, x, y) / api.goToTime(id, x, y, time_sec)
# api.setTarget(x, y, time_sec)
# api.setTraceRoute(cells, time_sec)
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

    loop_dt = 0.05
    resend_same_target_sec = 0.25
    move_time_sec = 1
    target_visual_sec = 0.35
    dead_zone_cells = 1

    elapsed = 0.0
    coord_cache: dict[str, dict[str, int]] = {}

    def clamp_cell_2x2(x: int, y: int) -> tuple[int, int]:
        # Pacman occupies 2x2 cells, so target anchor must allow +1 on both axes
        x = max(0, min(layout.map_w_cells - 2, x))
        y = max(0, min(layout.map_h_cells - 2, y))
        return x, y

    def is_likely_wall(x: int, y: int) -> bool:
        try:
            v = api.getBlockInfo(x, y)
            if isinstance(v, bool):
                return v
            return False
        except Exception:
            return False

    def is_free_2x2(x: int, y: int) -> bool:
        x, y = clamp_cell_2x2(x, y)
        return not (
            is_likely_wall(x, y)
            or is_likely_wall(x + 1, y)
            or is_likely_wall(x, y + 1)
            or is_likely_wall(x + 1, y + 1)
        )

    def find_reachable_candidate(
        desired_x: int,
        desired_y: int,
        from_x: int,
        from_y: int,
    ) -> tuple[tuple[int, int], list[tuple[int, int]]] | None:
        desired_x, desired_y = clamp_cell_2x2(desired_x, desired_y)
        from_x, from_y = clamp_cell_2x2(from_x, from_y)

        if not is_free_2x2(from_x, from_y):
            nearest_start = None
            best_start_d2 = 10**9
            for yy in range(0, layout.map_h_cells - 1):
                for xx in range(0, layout.map_w_cells - 1):
                    if not is_free_2x2(xx, yy):
                        continue
                    d2 = (xx - from_x) * (xx - from_x) + (yy - from_y) * (yy - from_y)
                    if d2 < best_start_d2:
                        best_start_d2 = d2
                        nearest_start = (xx, yy)
            if nearest_start is None:
                return None
            from_x, from_y = nearest_start

        start = (from_x, from_y)
        q: deque[tuple[int, int]] = deque([start])
        visited = {start}
        parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}

        best = start
        best_d2 = (start[0] - desired_x) * (start[0] - desired_x) + (start[1] - desired_y) * (start[1] - desired_y)

        while q:
            cx, cy = q.popleft()
            d2 = (cx - desired_x) * (cx - desired_x) + (cy - desired_y) * (cy - desired_y)
            if d2 < best_d2:
                best_d2 = d2
                best = (cx, cy)

            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cx + dx, cy + dy
                if nx < 0 or ny < 0 or nx > layout.map_w_cells - 2 or ny > layout.map_h_cells - 2:
                    continue
                nxt = (nx, ny)
                if nxt in visited:
                    continue
                if not is_free_2x2(nx, ny):
                    continue
                visited.add(nxt)
                parent[nxt] = (cx, cy)
                q.append(nxt)

        path: list[tuple[int, int]] = []
        cur: tuple[int, int] | None = best
        while cur is not None:
            path.append(cur)
            cur = parent.get(cur)
        path.reverse()

        return best, path

    while True:
        for line in mqtt_ctrl.drain_logs():
            print(line)

        for sample in mqtt_ctrl.drain_samples():
            payload = sample.payload
            mode = payload.get("mode", INPUT_MODE)
            trace_enabled = mode == "#trace"
            if mode == "#trace":
                mode = "#coordinates"
            player_name = _extract_player_name(payload, sample.topic) or "default"

            print(
                f"[MQTT] sample topic={sample.topic} "
                f"player={player_name} mode={mode} payload={payload}"
            )

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
                    topic_axis = topic_parts[-1] if topic_parts else ""
                    cached = coord_cache.get(player_name, {})
                    if topic_axis == "z":
                        print(
                            f"[MQTT] waiting x+y player={player_name}: got z only, "
                            f"cached_x={cached.get('x')} cached_y={cached.get('y')}"
                        )
                    elif topic_axis in {"x", "y"}:
                        print(
                            f"[MQTT] waiting x+y player={player_name}: got {topic_axis}, "
                            f"cached_x={cached.get('x')} cached_y={cached.get('y')}"
                        )
                    else:
                        print(
                            f"[MQTT] coordinates not parsed player={player_name} "
                            f"topic={sample.topic} payload={payload}"
                        )
            else:
                res = geom.payload_to_cells(payload)
                if res is not None:
                    pos_m, pos_c = res

            if pos_c is not None:
                player_name = _extract_player_name(payload, sample.topic) or "default"

                prev_input = last_input_cell_by_player.get(player_name)
                cur_input = (pos_c.x, pos_c.y)
                if prev_input != cur_input:
                    print(
                        f"[MQTT] coordinates changed player={player_name} "
                        f"from={prev_input} to={cur_input}"
                    )
                else:
                    print(
                        f"[MQTT] coordinates unchanged player={player_name} "
                        f"cell={cur_input}"
                    )
                last_input_cell_by_player[player_name] = cur_input

                if player_name not in player_ids:
                    player_ids[player_name] = next_player_id
                    api.spawn(next_player_id, 1, 3)
                    api.stop(next_player_id)
                    last_target_cell_by_player[player_name] = None
                    last_send_ts_by_player[player_name] = 0.0
                    print(f"[UWB] player connected: {player_name} -> id={next_player_id}")
                    next_player_id += 1

                pac_id = player_ids[player_name]

                last_target_cell = last_target_cell_by_player.get(player_name)
                last_send_ts = last_send_ts_by_player.get(player_name, 0.0)
                from_x, from_y = last_target_cell or (0, 2)

                reachable_res = find_reachable_candidate(
                    pos_c.x,
                    pos_c.y,
                    from_x,
                    from_y,
                )
                if reachable_res is None:
                    api.stop(pac_id)
                    print(
                        f"[MQTT] no reachable 2x2 target player={player_name} id={pac_id} "
                        f"requested=({pos_c.x},{pos_c.y}) -> stop"
                    )
                    continue

                (tx, ty), trace_path = reachable_res
                if (tx, ty) != (pos_c.x, pos_c.y):
                    print(
                        f"[MQTT] target adjusted player={player_name} "
                        f"requested=({pos_c.x},{pos_c.y}) adjusted=({tx},{ty})"
                    )

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
                    if trace_enabled:
                        trace_cells = [(px + 1, py + 1) for px, py in trace_path]
                        api.setTraceRoute(trace_cells, 1.0)
                    else:
                        api.setTarget(tx + 1, ty + 1, target_visual_sec)
                    api.goToTime(pac_id, tx + 1, ty + 1, move_time_sec)

                    last_target_cell_by_player[player_name] = (tx, ty)
                    last_send_ts_by_player[player_name] = elapsed

                    print(
                        f"[MQTT] command sent player={player_name} id={pac_id} "
                        f"target_cell=({tx},{ty}) visual=({tx + 1},{ty + 1})"
                    )

                    if pos_m is not None:
                        print(
                            f"[UWB] player={player_name} meters=({pos_m.x:.2f},{pos_m.y:.2f}) "
                            f"-> cell=({pos_c.x},{pos_c.y}) -> cmd=({tx},{ty})"
                        )
                    else:
                        print(
                            f"[UWB] player={player_name} coordinates mode "
                            f"-> cell=({pos_c.x},{pos_c.y}) -> cmd=({tx},{ty})"
                        )
                else:
                    print(
                        f"[MQTT] command skipped player={player_name} id={pac_id} "
                        f"target_cell=({tx},{ty}) last_target={last_target_cell} "
                        f"elapsed={elapsed:.2f} last_send={last_send_ts:.2f}"
                    )

        yield api.wait(loop_dt)
        elapsed += loop_dt
