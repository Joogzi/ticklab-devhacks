"""Player state and the per-tick update."""
from . import input as inp
from . import physics


class Player:
    def __init__(self, state: dict | None = None):
        s = state or {}
        self.x = float(s.get("x", 0.5))
        self.y = float(s.get("y", 100.0))
        self.z = float(s.get("z", 0.5))
        self.vx = float(s.get("vx", 0.0))
        self.vy = float(s.get("vy", -0.0784000015258789))
        self.vz = float(s.get("vz", 0.0))
        self.yaw = float(s.get("yaw", 0.0))
        self.pitch = float(s.get("pitch", 0.0))
        self.on_ground = bool(s.get("on_ground", True))
        self.sprinting = bool(s.get("sprinting", False))
        self.crouching = bool(s.get("sneaking", False))
        self.pose = s.get("pose", "STANDING")
        self.horizontal_collision = False
        self.minor_horizontal_collision = False
        self.xxa = 0.0
        self.zza = 0.0
        self.no_jump_delay = 0
        self.speed = physics.movement_speed(self.sprinting)
        self.last_keys = inp.Keys()

    def tick(self, keys: inp.Keys, world) -> None:
        # Client input step: crouch state comes from the shift key as of the previous tick.
        self.crouching = self.last_keys.shift
        move = inp.move_vector(keys)
        self.last_keys = keys.copy()
        forward = move[1] > 1.0e-5
        if not self.sprinting and forward and not self.crouching and keys.sprint:
            self.sprinting = True
        if self.sprinting and (not forward or (self.horizontal_collision and not self.minor_horizontal_collision)):
            self.sprinting = False

        # Movement speed follows the sprint state of this tick (real 26.3 traces: no one-tick lag).
        self.speed = physics.movement_speed(self.sprinting)

        # Living-entity step.
        if self.no_jump_delay > 0:
            self.no_jump_delay -= 1
        physics.apply_threshold(self)
        xxa, zza = inp.modify_input(move, self.crouching)
        self.xxa, self.zza = xxa, zza
        if keys.jump:
            if self.on_ground and self.no_jump_delay == 0:
                physics.jump_from_ground(self)
                self.no_jump_delay = physics.JUMP_COOLDOWN
        else:
            self.no_jump_delay = 0
        physics.travel(self, world, xxa, zza)

        # End of the player step: refresh pose.
        self.pose = "CROUCHING" if keys.shift else "STANDING"

    def state(self) -> dict:
        return {"x": self.x, "y": self.y, "z": self.z, "vx": self.vx, "vy": self.vy, "vz": self.vz,
                "on_ground": self.on_ground, "yaw": self.yaw, "pitch": self.pitch, "pose": self.pose,
                "sprinting": self.sprinting, "sneaking": self.crouching}
