from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, SimpleQueue
from threading import Thread
from tkinter import BOTH, LEFT, RIGHT, Button, Checkbutton, Frame, IntVar, Label, Tk, W, ttk


@dataclass
class ControlCommand:
    name: str
    value: int | bool | None = None


class ControlPanel:
    def __init__(self):
        self._queue: SimpleQueue[ControlCommand] = SimpleQueue()
        self._started = False
        self._level_var: IntVar | None = None
        self._ghosts_var: IntVar | None = None
        self._fullscreen_var: IntVar | None = None

    @property
    def is_started(self) -> bool:
        return self._started

    def start(self, max_level: int) -> None:
        if self._started:
            return
        self._started = True
        worker = Thread(target=self._run_ui, args=(max_level,), daemon=True)
        worker.start()

    def _run_ui(self, max_level: int) -> None:
        root = Tk()
        root.title("Pacman Control")
        root.geometry("320x230")
        root.resizable(False, False)

        body = Frame(root, padx=10, pady=10)
        body.pack(fill=BOTH, expand=True)

        self._ghosts_var = IntVar(value=1)
        self._fullscreen_var = IntVar(value=1)
        self._level_var = IntVar(value=1)

        Label(body, text="Управление уровнем").pack(anchor=W)

        ghosts_toggle = Checkbutton(
            body,
            text="Приведения включены",
            variable=self._ghosts_var,
            command=lambda: self._queue.put(ControlCommand("ghosts", bool(self._ghosts_var.get()))),
        )
        ghosts_toggle.pack(anchor=W, pady=(6, 0))

        fs_toggle = Checkbutton(
            body,
            text="Полноэкранный режим",
            variable=self._fullscreen_var,
            command=lambda: self._queue.put(ControlCommand("fullscreen", bool(self._fullscreen_var.get()))),
        )
        fs_toggle.pack(anchor=W, pady=(6, 8))

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
        rotate_row.pack(fill=BOTH, pady=(8, 0))
        Label(rotate_row, text="Ориентация:").pack(side=LEFT)
        Button(rotate_row, text="↶", width=6, command=lambda: self._queue.put(ControlCommand("rotate_left"))).pack(side=LEFT, padx=6)
        Button(rotate_row, text="↷", width=6, command=lambda: self._queue.put(ControlCommand("rotate_right"))).pack(side=LEFT)

        root.mainloop()

    def read_commands(self) -> list[ControlCommand]:
        commands: list[ControlCommand] = []
        while True:
            try:
                commands.append(self._queue.get_nowait())
            except Empty:
                return commands


control_panel = ControlPanel()
