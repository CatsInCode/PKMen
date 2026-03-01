from pygame import FULLSCREEN, KEYDOWN, KMOD_CTRL, QUIT, SCALED, K_q, display, event, time, transform
from pygame.event import Event

from pacman.data_core import Cfg, EvenType, PathUtl
from pacman.control_panel import control_panel
from pacman.misc import GameObjects
from pacman.objects import KbEvent
from pacman.scenes import SceneManager
from pacman.scenes.main_scene import MainScene
from pacman.scenes.menu_scene import MenuScene
from pacman.sound import SoundController, Sounds
from pacman.storage import StorageLoader


class Game:
    def __init__(self) -> None:
        self.__objects = GameObjects()

        self.__fullscreen = False
        self.__rotation = 0
        self.__restart_on_rotate = False
        self.__apply_display_mode()
        self.__clock = time.Clock()

        self.__storage_loader = StorageLoader(PathUtl.get("storage.json"))

        self.__storage_loader.from_file()
        SoundController.update_volume()

        self.__objects += [self.__storage_loader, KbEvent()]

        SceneManager().reset(MenuScene())

    # region Exit

    @staticmethod
    def __exit_hotkey_pressed(e: Event) -> bool:
        return e.type == KEYDOWN and e.mod & KMOD_CTRL and e.key == K_q

    def __process_exit_events(self, e: Event) -> None:
        if e.type in (QUIT, EvenType.EXIT) or Game.__exit_hotkey_pressed(e):
            self.exit_game()

    def exit_game(self) -> None:
        self.__storage_loader.to_file()
        print("Bye bye")
        exit()

    # endregion

    def __display_resolution(self) -> tuple[int, int]:
        if self.__restart_on_rotate and self.__rotation % 180:
            return Cfg.RESOLUTION.HEIGHT, Cfg.RESOLUTION.WIDTH
        return tuple(Cfg.RESOLUTION)

    def __apply_display_mode(self) -> None:
        flags = SCALED | (FULLSCREEN if self.__fullscreen else 0)
        display.set_mode(self.__display_resolution(), flags)

    def __restart_current_scene(self) -> None:
        scene_manager = SceneManager()
        if isinstance(scene_manager.current, MainScene):
            scene_manager.reset(MainScene())
            return
        if isinstance(scene_manager.current, MenuScene):
            scene_manager.reset(MenuScene())
            return
        scene_manager.current.setup()

    def __handle_rotation_change(self) -> None:
        if self.__restart_on_rotate:
            self.__apply_display_mode()
            self.__restart_current_scene()

    def __process_control_panel(self) -> None:
        scene_manager = SceneManager()
        if isinstance(scene_manager.current, MainScene) and not control_panel.is_started:
            from pacman.storage import LevelStorage

            control_panel.start(LevelStorage().len)
        for cmd in control_panel.read_commands():
            if cmd.name == "ghosts" and isinstance(scene_manager.current, MainScene):
                scene_manager.current.set_ghosts_enabled(bool(cmd.value))
            elif cmd.name == "level":
                from pacman.storage import LevelStorage

                level_storage = LevelStorage()
                while level_storage.len_unlocked < level_storage.len:
                    level_storage.unlock_next_level()
                level_storage.current = int(cmd.value)
                scene_manager.reset(MainScene())
            elif cmd.name == "rotate_left":
                self.__rotation = (self.__rotation - 90) % 360
                self.__handle_rotation_change()
            elif cmd.name == "rotate_right":
                self.__rotation = (self.__rotation + 90) % 360
                self.__handle_rotation_change()
            elif cmd.name == "restart_on_rotate":
                self.__restart_on_rotate = bool(cmd.value)
                self.__apply_display_mode()
            elif cmd.name == "fullscreen":
                self.__fullscreen = bool(cmd.value)
                self.__apply_display_mode()

    # region Game Loop

    def __process_all_events(self) -> None:
        for e in event.get():
            self.__objects.event_handler(e)
            Sounds.event_handler(e)
            SceneManager().current.process_event(e)
            self.__process_exit_events(e)

    def __process_all_logic(self) -> None:
        SceneManager().current.process_logic()

    def __process_all_draw(self) -> None:
        screen = display.get_surface()
        frame = SceneManager().current.draw()

        if self.__rotation:
            rotated = transform.rotate(frame, self.__rotation)
            screen_w, screen_h = screen.get_size()
            frame_w, frame_h = rotated.get_size()
            scale = min(screen_w / frame_w, screen_h / frame_h)
            target_size = (max(1, int(frame_w * scale)), max(1, int(frame_h * scale)))
            fitted = transform.smoothscale(rotated, target_size)
            frame_rect = fitted.get_rect(center=screen.get_rect().center)
            screen.fill((0, 0, 0))
            screen.blit(fitted, frame_rect)
        else:
            screen.blit(frame, (0, 0))

        display.flip()

    def main_loop(self) -> None:
        while True:
            self.__process_all_events()
            self.__process_control_panel()
            self.__process_all_logic()
            self.__process_all_draw()
            self.__clock.tick(Cfg.FPS)

    # endregion
