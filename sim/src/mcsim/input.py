"""Key state -> movement input vector (float math, like the client's keyboard input)."""
from dataclasses import dataclass

from .fmath import f32, fmul, fdiv, fsqrt

KEYS = ("forward", "backward", "left", "right", "jump", "shift", "sprint")
SNEAK_SPEED = f32(0.3)


@dataclass
class Keys:
    forward: bool = False
    backward: bool = False
    left: bool = False
    right: bool = False
    jump: bool = False
    shift: bool = False
    sprint: bool = False

    def copy(self) -> "Keys":
        return Keys(**self.__dict__)


def _impulse(pos: bool, neg: bool) -> float:
    if pos == neg:
        return 0.0
    return 1.0 if pos else -1.0


def _length(x: float, y: float) -> float:
    return fsqrt(f32(fmul(x, x) + fmul(y, y)))


def _scale(v, s):
    return (fmul(v[0], s), fmul(v[1], s))


def move_vector(keys: Keys):
    """Raw (left, forward) impulse, normalized to unit length."""
    x = _impulse(keys.left, keys.right)
    y = _impulse(keys.forward, keys.backward)
    n = _length(x, y)
    if n < f32(1.0e-4):
        return (0.0, 0.0)
    return (fdiv(x, n), fdiv(y, n))


def _to_unit_square(v):
    n = _length(v[0], v[1])
    if n <= 0.0:
        return v
    u = _scale(v, fdiv(1.0, n))
    ax, ay = abs(u[0]), abs(u[1])
    r = fdiv(ax, ay) if ay > ax else fdiv(ay, ax)
    k = fsqrt(f32(1.0 + fmul(r, r)))
    return _scale(u, min(fmul(n, k), 1.0))


def modify_input(v, moving_slowly: bool):
    """Scale the move vector: 0.98 damping, sneak slowdown, then map the circle onto the unit square."""
    if fmul(v[0], v[0]) + fmul(v[1], v[1]) == 0.0:
        return v
    v = _scale(v, f32(0.98))
    if moving_slowly:
        v = _scale(v, SNEAK_SPEED)
    return _to_unit_square(v)
