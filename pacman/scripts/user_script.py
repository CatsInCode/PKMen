from __future__ import annotations


# Edit only this function.
# Commands available:
## x/y are map cell coordinates
# api.spawn(id, x, y)
# api.remove(id)
# api.up(id) / api.right(id) / api.left(id) / api.down(id) / api.stop(id)
# api.goTo(id, x, y) / api.goToTime(id, x, y, time_sec)
# api.setTarget(x, y, time_sec)
# yield api.wait(seconds)
# yield api.wait_key("u")
def build_script(api):
    while True:
        # Write your own scenario here.
        # Example:
        # api.spawn(1, 48, 48)
        # api.right(1)
        # yield api.wait(2.0)
        # api.left(1)
        # yield api.wait(2.0)
        # yield api.wait_key("u")
        # api.up(1)
        yield api.wait(0.1)
