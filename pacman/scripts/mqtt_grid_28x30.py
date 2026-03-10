from __future__ import annotations

import json
import os
import queue
import random
import socket
import time
from dataclasses import dataclass
from typing import Any, Optional

import tkinter as tk
import paho.mqtt.client as mqtt


# =========================
# Настройки
# =========================
MQTT_HOST = "192.168.10.118"
MQTT_PORT = 1883
MQTT_TOPIC = "uwb/tag/#"
MQTT_KEEPALIVE = 30

TARGET_PLAYER = "pac1"

GRID_COLS = 14
GRID_ROWS = 15
CELL_SIZE = 24
PADDING = 20

BG_COLOR = "#111111"
GRID_COLOR = "#303030"
DOT_COLOR = "#ff2b2b"
TEXT_COLOR = "#dddddd"


@dataclass
class MqttSample:
    topic: str
    payload: dict[str, Any]


class MqttReceiver:
    def __init__(
        self,
        host: str = MQTT_HOST,
        port: int = MQTT_PORT,
        topic: str = MQTT_TOPIC,
        keepalive: int = MQTT_KEEPALIVE,
        client_id: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.topic = topic
        self.keepalive = keepalive

        if client_id is None:
            hostn = socket.gethostname().replace(" ", "_")
            pid = os.getpid()
            rnd = random.randint(1000, 9999)
            ts = int(time.time() * 1000) % 1_000_000
            client_id = f"mqtt_grid_{hostn}_{pid}_{ts}_{rnd}"

        self.client_id = client_id
        self.connected = False

        self._q: queue.Queue[MqttSample] = queue.Queue()
        self._log_q: queue.Queue[str] = queue.Queue()
        self._coord_cache: dict[str, dict[str, int]] = {}

        self._client = mqtt.Client(client_id=self.client_id)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    def start(self) -> None:
        try:
            self._client.connect(self.host, self.port, keepalive=self.keepalive)
            self._client.loop_start()
            self._log_q.put(f"[MQTT] start client_id={self.client_id}")
        except Exception as e:
            self._log_q.put(f"[MQTT] connect/start error: {e}")

    def stop(self) -> None:
        try:
            self._client.loop_stop()
        except Exception:
            pass
        try:
            self._client.disconnect()
        except Exception:
            pass

    def _on_connect(self, client, userdata, flags, rc):
        self.connected = (rc == 0)
        self._log_q.put(f"[MQTT] connected rc={rc}")
        if rc == 0:
            client.subscribe(self.topic, qos=0)
            self._log_q.put(f"[MQTT] subscribed: {self.topic}")

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        self._log_q.put(f"[MQTT] disconnected rc={rc}")

    def _on_message(self, client, userdata, msg):
        try:
            text = msg.payload.decode("utf-8", errors="replace").strip()
            data = json.loads(text)

            if isinstance(data, dict):
                payload = data
            elif isinstance(data, (int, float, str)):
                payload = {"value": data}
            else:
                return

            self._q.put(MqttSample(topic=msg.topic, payload=payload))
        except Exception as e:
            self._log_q.put(f"[MQTT] bad message: {e}")

    def drain_logs(self) -> list[str]:
        out: list[str] = []
        while True:
            try:
                out.append(self._log_q.get_nowait())
            except queue.Empty:
                break
        return out

    def drain_samples(self) -> list[MqttSample]:
        out: list[MqttSample] = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                break
        return out

    def extract_position(self, topic: str, payload: dict[str, Any]) -> tuple[str, int, int] | None:
        """
        Поддерживает ту же логику:
        1) split-topic:
           uwb/tag/coordinates/<name>/x|y|z
           payload: {"value": ...}
        2) direct payload:
           payload: {"x": 4, "y": 7, "name": "pac1"}

        Но принимает только TARGET_PLAYER.
        """
        from_topic = self._extract_coordinates_from_topic_value(topic, payload)
        if from_topic is not None:
            player_name, x, y = from_topic
            if player_name == TARGET_PLAYER:
                return player_name, x, y
            return None

        from_payload = self._extract_coordinates_from_payload(topic, payload)
        if from_payload is not None:
            player_name, x, y = from_payload
            if player_name == TARGET_PLAYER:
                return player_name, x, y
            return None

        return None

    def _extract_coordinates_from_payload(
        self, topic: str, payload: dict[str, Any]
    ) -> tuple[str, int, int] | None:
        def first_number(*keys: str) -> Optional[int]:
            for key in keys:
                value = payload.get(key)
                if isinstance(value, (int, float)):
                    return int(round(value))
                if isinstance(value, str):
                    try:
                        return int(round(float(value)))
                    except ValueError:
                        continue
            return None

        x = first_number("x", "X", "cell_x", "cx")
        y = first_number("y", "Y", "cell_y", "cy")
        if x is None or y is None:
            return None

        player_name = self._extract_player_name(payload, topic) or "default"
        return player_name, x, y

    def _extract_coordinates_from_topic_value(
        self, topic: str, payload: dict[str, Any]
    ) -> tuple[str, int, int] | None:
        prefix = "uwb/tag/coordinates/"
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

        if name not in self._coord_cache:
            self._coord_cache[name] = {}

        self._coord_cache[name][axis] = int(round(value))

        x = self._coord_cache[name].get("x")
        y = self._coord_cache[name].get("y")
        if x is None or y is None:
            return None

        return name, x, y

    @staticmethod
    def _extract_player_name(payload: dict[str, Any], topic: str) -> str | None:
        name = payload.get("name") or payload.get("player")
        if isinstance(name, str) and name.strip():
            return name.strip()

        prefix = "uwb/tag/coordinates/"
        if topic.startswith(prefix):
            parts = [p for p in topic[len(prefix):].split("/") if p]
            if parts:
                return parts[0].strip() or None

        return None


class GridApp:
    def __init__(self) -> None:
        self.receiver = MqttReceiver()

        self.root = tk.Tk()
        self.root.title(f"MQTT Grid 28x30 [{TARGET_PLAYER}]")
        self.root.configure(bg=BG_COLOR)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.canvas_w = GRID_COLS * CELL_SIZE + PADDING * 2
        self.canvas_h = GRID_ROWS * CELL_SIZE + PADDING * 2

        self.canvas = tk.Canvas(
            self.root,
            width=self.canvas_w,
            height=self.canvas_h,
            bg=BG_COLOR,
            highlightthickness=0,
        )
        self.canvas.pack(padx=10, pady=(10, 6))

        self.status_var = tk.StringVar(value="MQTT: connecting...")
        self.pos_var = tk.StringVar(value=f"x=—  y=—  player={TARGET_PLAYER}")

        self.status_label = tk.Label(
            self.root, textvariable=self.status_var, bg=BG_COLOR, fg=TEXT_COLOR, anchor="w"
        )
        self.status_label.pack(fill="x", padx=12)

        self.pos_label = tk.Label(
            self.root, textvariable=self.pos_var, bg=BG_COLOR, fg=TEXT_COLOR, anchor="w"
        )
        self.pos_label.pack(fill="x", padx=12, pady=(0, 10))

        self.dot_id: int | None = None
        self.current_player = TARGET_PLAYER
        self.current_x: int | None = None
        self.current_y: int | None = None
        self.last_message_at: float | None = None

        self._draw_grid()
        self.receiver.start()
        self._poll()

    def _draw_grid(self) -> None:
        left = PADDING
        top = PADDING
        right = left + GRID_COLS * CELL_SIZE
        bottom = top + GRID_ROWS * CELL_SIZE

        for col in range(GRID_COLS + 1):
            x = left + col * CELL_SIZE
            self.canvas.create_line(x, top, x, bottom, fill=GRID_COLOR)

        for row in range(GRID_ROWS + 1):
            y = top + row * CELL_SIZE
            self.canvas.create_line(left, y, right, y, fill=GRID_COLOR)

        self.canvas.create_rectangle(left, top, right, bottom, outline="#666666", width=2)

    def _cell_center(self, x: int, y: int) -> tuple[float, float]:
        clamped_x = max(0, min(GRID_COLS - 1, x))
        clamped_y = max(0, min(GRID_ROWS - 1, y))

        cx = PADDING + clamped_x * CELL_SIZE + CELL_SIZE / 2
        cy = PADDING + clamped_y * CELL_SIZE + CELL_SIZE / 2
        return cx, cy

    def _draw_dot(self, x: int, y: int) -> None:
        cx, cy = self._cell_center(x, y)
        r = max(4, CELL_SIZE * 0.28)

        if self.dot_id is None:
            self.dot_id = self.canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                fill=DOT_COLOR, outline=""
            )
        else:
            self.canvas.coords(self.dot_id, cx - r, cy - r, cx + r, cy + r)

    def _poll(self) -> None:
        for log_line in self.receiver.drain_logs():
            print(log_line)
            if "connected rc=0" in log_line:
                self.status_var.set(f"MQTT: connected to {self.receiver.host}:{self.receiver.port}")
            elif "subscribed:" in log_line:
                self.status_var.set(
                    f"MQTT: subscribed {self.receiver.topic} | target={TARGET_PLAYER}"
                )
            elif "connect/start error" in log_line:
                self.status_var.set(f"MQTT error: {log_line}")
            elif "disconnected" in log_line:
                self.status_var.set("MQTT: disconnected")

        latest_position: tuple[str, int, int] | None = None

        for sample in self.receiver.drain_samples():
            pos = self.receiver.extract_position(sample.topic, sample.payload)
            if pos is not None:
                latest_position = pos

        if latest_position is not None:
            player, x, y = latest_position
            self.current_player = player
            self.current_x = max(0, min(GRID_COLS - 1, x))
            self.current_y = max(0, min(GRID_ROWS - 1, y))
            self.last_message_at = time.time()

            self._draw_dot(self.current_x, self.current_y)
            self.pos_var.set(
                f"x={self.current_x}  y={self.current_y}  player={self.current_player}"
            )

        if self.last_message_at is not None and time.time() - self.last_message_at > 3:
            if self.receiver.connected:
                self.status_var.set(
                    f"MQTT: connected, waiting data for {TARGET_PLAYER}"
                )

        self.root.after(50, self._poll)

    def on_close(self) -> None:
        self.receiver.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    GridApp().run()
