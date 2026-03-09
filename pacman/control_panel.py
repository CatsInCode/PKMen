from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, SimpleQueue
from threading import Thread
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
        root.geometry("360x300")
        root.resizable(False, False)

        body = Frame(root, padx=10, pady=10)
        body.pack(fill=BOTH, expand=True)

        self._fullscreen_var = IntVar(value=1)
        self._restart_on_rotate_var = IntVar(value=0)

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
        restart_rotate_toggle.pack(anchor=W, pady=(6, 8))

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
