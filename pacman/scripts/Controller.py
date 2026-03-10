import json
import math
import tkinter as tk
from tkinter import ttk

import paho.mqtt.client as mqtt


class MqttMouseFieldController:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("MQTT Mouse Field Controller")
        self.root.geometry("1180x780")
        self.root.minsize(980, 680)

        self.client: mqtt.Client | None = None
        self.connected = False
        self.running = False

        self.current_cell_x = 0
        self.current_cell_y = 0
        self.last_sent_cell: tuple[int, int] | None = None
        self.last_send_ms = 0

        self._build_ui()
        self._apply_canvas_size()
        self._schedule_loop()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill="both", expand=True)

        container.columnconfigure(0, weight=0)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(0, weight=1)

        left = ttk.Frame(container)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))

        right = ttk.Frame(container)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        # ---------- settings ----------
        settings = ttk.LabelFrame(left, text="Настройки", padding=10)
        settings.pack(fill="x")

        self.host_var = tk.StringVar(value="192.168.10.118")
        self.port_var = tk.StringVar(value="1883")
        self.player_var = tk.StringVar(value="pac1")
        self.topic_prefix_var = tk.StringVar(value="uwb/tag/coordinates")
        self.field_w_var = tk.StringVar(value="28")
        self.field_h_var = tk.StringVar(value="31")
        self.cell_px_var = tk.StringVar(value="22")
        self.send_hz_var = tk.StringVar(value="20")
        self.send_only_changes_var = tk.BooleanVar(value=False)
        self.send_z_var = tk.BooleanVar(value=False)

        self._row_entry(settings, 0, "MQTT host", self.host_var)
        self._row_entry(settings, 1, "MQTT port", self.port_var)
        self._row_entry(settings, 2, "Имя игрока", self.player_var)
        self._row_entry(settings, 3, "Topic prefix", self.topic_prefix_var)
        self._row_entry(settings, 4, "Ширина поля", self.field_w_var)
        self._row_entry(settings, 5, "Высота поля", self.field_h_var)
        self._row_entry(settings, 6, "Размер клетки px", self.cell_px_var)
        self._row_entry(settings, 7, "Частота отправки, Гц", self.send_hz_var)

        ttk.Checkbutton(
            settings,
            text="Отправлять только при смене клетки",
            variable=self.send_only_changes_var,
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Checkbutton(
            settings,
            text="Отправлять ещё и z=0",
            variable=self.send_z_var,
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(4, 0))

        buttons = ttk.Frame(settings)
        buttons.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        buttons.columnconfigure((0, 1), weight=1)

        self.connect_btn = ttk.Button(buttons, text="Подключиться", command=self.toggle_connection)
        self.connect_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        ttk.Button(buttons, text="Применить поле", command=self._apply_canvas_size).grid(
            row=0, column=1, sticky="ew", padx=(4, 0)
        )

        self.status_var = tk.StringVar(value="Статус: отключено")
        ttk.Label(settings, textvariable=self.status_var, foreground="#1f5f99").grid(
            row=11, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )

        hint = ttk.LabelFrame(left, text="Как это работает", padding=10)
        hint.pack(fill="x", pady=(12, 0))
        ttk.Label(
            hint,
            text=(
                "Наводи мышь на поле справа.\n"
                "Приложение отправляет координаты клетки в MQTT:\n"
                "<topic_prefix>/<player>/x\n"
                "<topic_prefix>/<player>/y\n"
                "Payload: {\"value\": число}\n\n"
                "Формат совместим с парсером тем\n"
                "uwb/tag/coordinates/<name>/x|y|z."
            ),
            justify="left",
        ).pack(anchor="w")

        # ---------- top info ----------
        top = ttk.Frame(right)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top.columnconfigure(0, weight=1)

        self.info_var = tk.StringVar(value="Клетка: x=0, y=0 | MQTT: не отправлено")
        ttk.Label(top, textvariable=self.info_var, font=("Segoe UI", 11, "bold")).pack(anchor="w")

        # ---------- canvas ----------
        canvas_wrap = ttk.Frame(right)
        canvas_wrap.grid(row=1, column=0, sticky="nsew")
        canvas_wrap.columnconfigure(0, weight=1)
        canvas_wrap.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(canvas_wrap, bg="#111318", highlightthickness=1, highlightbackground="#2e3440")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<Button-1>", self._on_mouse_move)
        self.canvas.bind("<Leave>", self._on_mouse_leave)

        log_frame = ttk.LabelFrame(right, text="Лог", padding=8)
        log_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)

        self.log = tk.Text(log_frame, height=10, wrap="word")
        self.log.grid(row=0, column=0, sticky="ew")
        self.log.configure(state="disabled")

    def _row_entry(self, parent: ttk.LabelFrame, row: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        ttk.Entry(parent, textvariable=variable, width=22).grid(row=row, column=1, sticky="ew", pady=4)
        parent.columnconfigure(1, weight=1)

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _safe_int(self, variable: tk.StringVar, default: int, minimum: int = 1, maximum: int = 10000) -> int:
        try:
            value = int(variable.get())
        except ValueError:
            value = default
        return max(minimum, min(maximum, value))

    def _safe_float(self, variable: tk.StringVar, default: float, minimum: float = 0.1, maximum: float = 1000.0) -> float:
        try:
            value = float(variable.get())
        except ValueError:
            value = default
        return max(minimum, min(maximum, value))

    def _field_size(self) -> tuple[int, int, int]:
        cols = self._safe_int(self.field_w_var, 28)
        rows = self._safe_int(self.field_h_var, 31)
        cell_px = self._safe_int(self.cell_px_var, 22, 8, 80)
        return cols, rows, cell_px

    def _apply_canvas_size(self) -> None:
        cols, rows, cell_px = self._field_size()
        width = cols * cell_px + 1
        height = rows * cell_px + 1
        self.canvas.config(width=width, height=height)
        self.current_cell_x = min(self.current_cell_x, cols - 1)
        self.current_cell_y = min(self.current_cell_y, rows - 1)
        self._draw_grid()
        self._append_log(f"Поле применено: {cols}x{rows}, клетка {cell_px}px")

    def _draw_grid(self) -> None:
        cols, rows, cell_px = self._field_size()
        self.canvas.delete("all")

        for y in range(rows):
            for x in range(cols):
                x1 = x * cell_px
                y1 = y * cell_px
                x2 = x1 + cell_px
                y2 = y1 + cell_px

                fill = "#1f232b"
                outline = "#343b48"
                if x == self.current_cell_x and y == self.current_cell_y:
                    fill = "#cc3333"
                    outline = "#ff7070"

                self.canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=1)
                self.canvas.create_text(
                    x1 + cell_px / 2,
                    y1 + cell_px / 2,
                    text=f"{x},{y}",
                    fill="#d8dee9",
                    font=("Consolas", max(7, min(11, cell_px // 3))),
                )

        self.canvas.create_text(
            8,
            8,
            anchor="nw",
            text="Води мышкой по клеткам",
            fill="#ffffff",
            font=("Segoe UI", 10, "bold"),
        )

    def _on_mouse_move(self, event) -> None:
        cols, rows, cell_px = self._field_size()
        x = max(0, min(cols - 1, event.x // cell_px))
        y = max(0, min(rows - 1, event.y // cell_px))

        if x != self.current_cell_x or y != self.current_cell_y:
            self.current_cell_x = x
            self.current_cell_y = y
            self._draw_grid()

        sent_info = "подготовлено"
        if self.last_sent_cell is not None:
            sent_info = f"последняя отправка x={self.last_sent_cell[0]}, y={self.last_sent_cell[1]}"
        self.info_var.set(f"Клетка: x={x}, y={y} | MQTT: {sent_info}")

    def _on_mouse_leave(self, _event) -> None:
        sent_info = "не отправлено" if self.last_sent_cell is None else f"последняя отправка x={self.last_sent_cell[0]}, y={self.last_sent_cell[1]}"
        self.info_var.set(f"Клетка: x={self.current_cell_x}, y={self.current_cell_y} | MQTT: {sent_info}")

    def toggle_connection(self) -> None:
        if self.running:
            self._disconnect()
        else:
            self._connect()

    def _connect(self) -> None:
        host = self.host_var.get().strip() or "127.0.0.1"
        port = self._safe_int(self.port_var, 1883, 1, 65535)

        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        try:
            self.client.connect(host, port, keepalive=30)
            self.client.loop_start()
            self.running = True
            self.connect_btn.config(text="Отключиться")
            self.status_var.set(f"Статус: подключение к {host}:{port}...")
            self._append_log(f"Подключение к MQTT: {host}:{port}")
        except Exception as e:
            self.running = False
            self.connected = False
            self.status_var.set(f"Статус: ошибка подключения: {e}")
            self._append_log(f"Ошибка подключения: {e}")

    def _disconnect(self) -> None:
        self.running = False
        self.connected = False
        try:
            if self.client is not None:
                self.client.loop_stop()
                self.client.disconnect()
        except Exception as e:
            self._append_log(f"Ошибка при отключении: {e}")
        self.client = None
        self.connect_btn.config(text="Подключиться")
        self.status_var.set("Статус: отключено")
        self._append_log("MQTT отключен")

    def _on_connect(self, client, userdata, flags, rc):
        self.connected = (rc == 0)
        if rc == 0:
            self.status_var.set("Статус: подключено")
            self._append_log("MQTT подключен")
        else:
            self.status_var.set(f"Статус: ошибка rc={rc}")
            self._append_log(f"MQTT connect rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        if self.running:
            self.status_var.set(f"Статус: соединение потеряно rc={rc}")
            self._append_log(f"MQTT disconnected rc={rc}")
        else:
            self.status_var.set("Статус: отключено")

    def _publish_coords(self) -> None:
        if not self.running or not self.connected or self.client is None:
            return

        player = self.player_var.get().strip() or "pac1"
        topic_prefix = self.topic_prefix_var.get().strip().strip("/") or "uwb/tag/coordinates"
        x = int(self.current_cell_x)
        y = int(self.current_cell_y)
        send_only_changes = self.send_only_changes_var.get()

        if send_only_changes and self.last_sent_cell == (x, y):
            return

        try:
            self.client.publish(f"{topic_prefix}/{player}/x", json.dumps({"value": x}), qos=0, retain=False)
            self.client.publish(f"{topic_prefix}/{player}/y", json.dumps({"value": y}), qos=0, retain=False)
            if self.send_z_var.get():
                self.client.publish(f"{topic_prefix}/{player}/z", json.dumps({"value": 0}), qos=0, retain=False)

            self.last_sent_cell = (x, y)
            self.info_var.set(f"Клетка: x={x}, y={y} | MQTT: последняя отправка x={x}, y={y}")
        except Exception as e:
            self._append_log(f"Ошибка publish: {e}")
            self.status_var.set(f"Статус: ошибка publish: {e}")

    def _schedule_loop(self) -> None:
        hz = self._safe_float(self.send_hz_var, 20.0, 0.5, 200.0)
        period_ms = max(5, int(1000.0 / hz))

        now_ms = int(self.root.tk.call("after", "info")[-1]) if False else 0
        # Используем monotonic-подобный таймер через tkinter after + счётчик времени от ОС.
        # Для простоты берём обычный time в момент вызова.
        import time
        current_ms = int(time.time() * 1000)
        if current_ms - self.last_send_ms >= period_ms:
            self.last_send_ms = current_ms
            self._publish_coords()

        self.root.after(10, self._schedule_loop)


def main() -> None:
    root = tk.Tk()
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    app = MqttMouseFieldController(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app._disconnect(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
