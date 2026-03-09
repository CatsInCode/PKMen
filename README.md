# Pacman
[![ci-status](https://github.com/BaggerFast/Pacman/workflows/CI/badge.svg)](https://github.com/BaggerFast/Pacman/actions/)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/BaggerFast/Pacman/main.svg)](https://results.pre-commit.ci/latest/github/BaggerFast/Pacman/main)
[![CodeFactor](https://www.codefactor.io/repository/github/baggerfast/pacman/badge)](https://www.codefactor.io/repository/github/baggerfast/pacman)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Imports: isort](https://img.shields.io/badge/%20imports-isort-%231674b1?style=flat&labelColor=ef8336)](https://pycqa.github.io/isort/)

Pacman is a simple game written on Pygame. The game was created as a learning project to explore
the possibilities of Pygame and develop game applications.

## 📺 Preview
https://github.com/BaggerFast/Pacman/assets/54527361/415e3585-086f-4111-822f-5049471ccbd8

Watch  full video on [YouTube](https://www.youtube.com/watch?v=VpNoZ70wDEg)

## 💻 Tech Stack
- [Python 3.10](https://www.python.org/)
- [Pygame](https://www.pygame.org/news)
- **Tools:**
  - [Black](https://github.com/psf/black)
  - [Isort](https://github.com/PyCQA/isort)
  - [PyLint](https://github.com/pylint-dev/pylint)
  - [CodeFactor](https://www.codefactor.io/)
    
## 👀 Look at this
- [Text](pacman/objects/text.py)
- [Button + controller](pacman/objects/buttons)
- [Sounds + controller](pacman/sound)
- [Scenes + SceneManager](pacman/scenes)
- [Animators + SpriteSheets](pacman/animator)
- [Saves - json serialize/deserialize](pacman/storage)

## 💾 Cheat codes
- In Game
  - **god** - victory scene
  - **kill** - lose scene
  - **aezakmi** - give 1 extra live
- In Menu
  - **pycman** - unlock all skins and levels

## 🎧 Set custom sounds in FUN MODE
![img.png](assets/fun_mode.png)

## 🚑 Support 
Please click the `star` button, if this game was helpful to you.


## 📡 MQTT UWB coordinates examples
If you use `pacman/scripts/user_script.py` with coordinates mode via topic,
publish messages to:

- `uwb/tag/coordinates/<name>` with JSON `{ "x": ..., "y": ... }`
- or split topics: `uwb/tag/coordinates/<name>/x` and `uwb/tag/coordinates/<name>/y`

Where `<name>` is the player name (for example, `ivan`). Coordinates are map cells.

```bash
# A) Single message with both coordinates
mosquitto_pub -h 192.168.0.110 -p 1883 \
  -t 'uwb/tag/coordinates/ivan' \
  -m '{"x": 10, "y": 20, "z": 0}'

# B) Split topics (as separate updates)
mosquitto_pub -h 192.168.0.110 -p 1883 \
  -t 'uwb/tag/coordinates/ivan/x' \
  -m '10'

mosquitto_pub -h 192.168.0.110 -p 1883 \
  -t 'uwb/tag/coordinates/ivan/y' \
  -m '20'

# Next movement for the same player (update only x)
mosquitto_pub -h 192.168.0.110 -p 1883 \
  -t 'uwb/tag/coordinates/ivan/x' \
  -m '30'
```
