from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, SimpleQueue
from threading import Lock, Thread
from tkinter import BOTH, LEFT, Button, Checkbutton, Frame, IntVar, Label, Spinbox, Tk, W, ttk


@dataclass
class ControlCommand:
    name: str
    value: int | bool | None = None


class ControlPanel:
    def __init__(self):
        self._queue: SimpleQueue[ControlCommand] = SimpleQueue()
        self._started = False
        self._fullscreen_var: IntVar | None = None
        self._restart_on_rotate_var: IntVar | None = None
        self._mqtt_invert_x_var: IntVar | None = None
        self._mqtt_invert_y_var: IntVar | None = None
        self._show_paths_var: IntVar | None = None
        self._mqtt_invert_x_enabled = True
        self._mqtt_invert_y_enabled = True
        self._active_players: list[str] = []
        self._active_players_lock = Lock()
        self._kick_queue: SimpleQueue[str] = SimpleQueue()

    @property
    def is_started(self) -> bool:
        return self._started


    def set_active_players(self, player_names: list[str]) -> None:
        with self._active_players_lock:
            self._active_players = sorted({str(name) for name in player_names if str(name).strip()})

    def _get_active_players(self) -> list[str]:
        with self._active_players_lock:
            return list(self._active_players)

    def queue_kick_player(self, player_name: str) -> None:
        if isinstance(player_name, str) and player_name.strip():
            self._kick_queue.put(player_name.strip())

    def drain_kick_players(self) -> list[str]:
        out: list[str] = []
        while True:
            try:
                out.append(self._kick_queue.get_nowait())
            except Empty:
                return out

    def set_mqtt_invert_x_enabled(self, value: bool) -> None:
        self._mqtt_invert_x_enabled = bool(value)

    def is_mqtt_invert_x_enabled(self) -> bool:
        return bool(self._mqtt_invert_x_enabled)

    def set_mqtt_invert_y_enabled(self, value: bool) -> None:
        self._mqtt_invert_y_enabled = bool(value)

    def is_mqtt_invert_y_enabled(self) -> bool:
        return bool(self._mqtt_invert_y_enabled)

    def start(self, max_level: int) -> None:
        if self._started:
            return
        self._started = True
        worker = Thread(target=self._run_ui, args=(max_level,), daemon=True)
        worker.start()

    def _run_ui(self, max_level: int) -> None:
        root = Tk()
        root.title("Pacman Control")
        root.geometry("420x460")
        root.resizable(False, False)

        body = Frame(root, padx=10, pady=10)
        body.pack(fill=BOTH, expand=True)

        self._fullscreen_var = IntVar(value=1)
        self._restart_on_rotate_var = IntVar(value=0)
        self._mqtt_invert_x_var = IntVar(value=1)
        self._mqtt_invert_y_var = IntVar(value=1)
        self._show_paths_var = IntVar(value=1)

        Label(body, text="Управление уровнем").pack(anchor=W)

        fs_toggle = Checkbutton(
            body,
            text="Полноэкранный режим",
            variable=self._fullscreen_var,
            command=lambda: self._queue.put(ControlCommand("fullscreen", bool(self._fullscreen_var.get()))),
        )
        fs_toggle.pack(anchor=W, pady=(6, 0))

        restart_rotate_toggle = Checkbutton(
            body,
            text="Перезапуск при смене ориентации (лучшее качество)",
            variable=self._restart_on_rotate_var,
            command=lambda: self._queue.put(
                ControlCommand("restart_on_rotate", bool(self._restart_on_rotate_var.get()))
            ),
        )
        restart_rotate_toggle.pack(anchor=W, pady=(6, 4))

        mqtt_invert_x_toggle = Checkbutton(
            body,
            text="Инвертировать MQTT X (28-x)",
            variable=self._mqtt_invert_x_var,
            command=lambda: self.set_mqtt_invert_x_enabled(bool(self._mqtt_invert_x_var.get())),
        )
        mqtt_invert_x_toggle.pack(anchor=W, pady=(2, 2))

        mqtt_invert_y_toggle = Checkbutton(
            body,
            text="Инвертировать MQTT Y (30-y)",
            variable=self._mqtt_invert_y_var,
            command=lambda: self.set_mqtt_invert_y_enabled(bool(self._mqtt_invert_y_var.get())),
        )
        mqtt_invert_y_toggle.pack(anchor=W, pady=(2, 4))

        show_paths_toggle = Checkbutton(
            body,
            text="Показывать путь (красная/зелёная точки)",
            variable=self._show_paths_var,
            command=lambda: self._queue.put(ControlCommand("show_paths", bool(self._show_paths_var.get()))),
        )
        show_paths_toggle.pack(anchor=W, pady=(2, 8))

        ghosts_row = Frame(body)
        ghosts_row.pack(fill=BOTH, pady=(2, 8))
        Label(ghosts_row, text="Кол-во привидений (0-4):").pack(side=LEFT)
        ghosts_spin = Spinbox(ghosts_row, from_=0, to=4, width=4)
        ghosts_spin.delete(0, "end")
        ghosts_spin.insert(0, "4")
        ghosts_spin.pack(side=LEFT, padx=8)
        Button(
            ghosts_row,
            text="Применить",
            command=lambda: self._queue.put(ControlCommand("ghost_count", int(ghosts_spin.get()))),
        ).pack(side=LEFT)

        level_row = Frame(body)
        level_row.pack(fill=BOTH, pady=(4, 8))
        Label(level_row, text="Уровень:").pack(side=LEFT)
        level_combo = ttk.Combobox(level_row, width=8, state="readonly", values=[str(i) for i in range(1, max_level + 1)])
        level_combo.current(0)
        level_combo.pack(side=LEFT, padx=(8, 8))

        def apply_level():
            current = max(1, int(level_combo.get())) - 1
            self._queue.put(ControlCommand("level", current))

        Button(level_row, text="Применить", command=apply_level).pack(side=LEFT)

        rotate_row = Frame(body)
        rotate_row.pack(fill=BOTH, pady=(8, 8))
        Label(rotate_row, text="Ориентация:").pack(side=LEFT)
        Button(rotate_row, text="↶", width=6, command=lambda: self._queue.put(ControlCommand("rotate_left"))).pack(side=LEFT, padx=6)
        Button(rotate_row, text="↷", width=6, command=lambda: self._queue.put(ControlCommand("rotate_right"))).pack(side=LEFT)

        players_box = Frame(body)
        players_box.pack(fill=BOTH, expand=True, pady=(4, 0))
        Label(players_box, text="Активные игроки:").pack(anchor=W)
        players_list = Frame(players_box)
        players_list.pack(fill=BOTH, expand=True, pady=(6, 0))

        def refresh_players():
            for child in players_list.winfo_children():
                child.destroy()
            players = self._get_active_players()
            if not players:
                Label(players_list, text="(нет)").pack(anchor=W)
            else:
                for name in players:
                    row = Frame(players_list)
                    row.pack(fill=BOTH, pady=1)
                    Label(row, text=name).pack(side=LEFT, anchor=W)
                    Button(row, text="✕", width=3, command=lambda n=name: self.queue_kick_player(n)).pack(side=LEFT, padx=8)
            root.after(300, refresh_players)

        refresh_players()
        root.mainloop()

    def read_commands(self) -> list[ControlCommand]:
        commands: list[ControlCommand] = []
        while True:
            try:
                commands.append(self._queue.get_nowait())
            except Empty:
                return commands


control_panel = ControlPanel()
