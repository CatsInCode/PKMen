from __future__ import annotations

import json
import os
import queue
import random
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import paho.mqtt.client as mqtt


@dataclass
class MqttSample:
    topic: str
    payload: dict[str, Any]


class MqttUwbController:
    def __init__(
        self,
        host: str = "192.168.0.110",
        port: int = 1883,
        topic_raw: str = "uwb/tag/raw",
        keepalive: int = 30,
        client_id: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.topic_raw = topic_raw
        self.keepalive = keepalive

        # Уникальный client_id по умолчанию
        if client_id is None:
            hostn = socket.gethostname().replace(" ", "_")
            pid = os.getpid()
            rnd = random.randint(1000, 9999)
            ts = int(time.time() * 1000) % 1_000_000
            client_id = f"pkmen2_uwb_receiver_{hostn}_{pid}_{ts}_{rnd}"

        self.client_id = client_id

        self._client = mqtt.Client(client_id=self.client_id)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._q: queue.Queue[MqttSample] = queue.Queue()
        self._log_q: queue.Queue[str] = queue.Queue()

        self.connected: bool = False
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True

        try:
            self._client.connect(self.host, self.port, keepalive=self.keepalive)
            self._client.loop_start()
            self._log_q.put(f"[MQTT] start client_id={self.client_id}")
        except Exception as e:
            self._log_q.put(f"[MQTT] connect/start error: {e}")

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            self._started = False
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
        self._log_q.put(f"[MQTT] connected rc={rc} client_id={self.client_id}")
        if rc == 0:
            client.subscribe(self.topic_raw, qos=0)
            self._log_q.put(f"[MQTT] subscribed: {self.topic_raw}")

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        self._log_q.put(f"[MQTT] disconnected rc={rc} client_id={self.client_id}")

    def _on_message(self, client, userdata, msg):
        try:
            text = msg.payload.decode("utf-8", errors="replace").strip()
            data = json.loads(text)
            if not isinstance(data, dict):
                return
            self._q.put(MqttSample(topic=msg.topic, payload=data))
        except Exception as e:
            self._log_q.put(f"[MQTT] bad message: {e}")

    def get_latest_sample(self) -> Optional[MqttSample]:
        latest: Optional[MqttSample] = None
        while True:
            try:
                latest = self._q.get_nowait()
            except queue.Empty:
                break
        return latest

    def drain_logs(self) -> list[str]:
        out: list[str] = []
        while True:
            try:
                out.append(self._log_q.get_nowait())
            except queue.Empty:
                break
        return out
