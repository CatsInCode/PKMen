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

    def __apply_display_mode(self) -> None:
        flags = SCALED | (FULLSCREEN if self.__fullscreen else 0)
        display.set_mode(tuple(Cfg.RESOLUTION), flags)

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
            elif cmd.name == "rotate_right":
                self.__rotation = (self.__rotation + 90) % 360
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
            frame = transform.rotate(frame, self.__rotation)
            frame_rect = frame.get_rect(center=screen.get_rect().center)
            screen.fill((0, 0, 0))
            screen.blit(frame, frame_rect)
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
