"""Movement physics: velocity threshold, jump, acceleration, collision move, gravity and drag."""
import math

from . import collision
from .fmath import DEG_TO_RAD_F, f32, fdiv, fmul, mth_cos, mth_sin

GRAVITY = 0.08
VERTICAL_DRAG = f32(0.98)
AIR_FRICTION = f32(0.91)
JUMP_POWER = f32(0.42)
JUMP_COOLDOWN = 10
SPRINT_JUMP_BOOST = 0.2
GROUND_ACCEL = f32(0.21600002)
AIR_SPEED = f32(0.02)
AIR_SPEED_SPRINTING = f32(0.025999999)
BASE_SPEED = 0.10000000149011612
SPRINT_MULTIPLIER = 0.30000001192092896
HALF_WIDTH = f32(0.6) / 2.0
HEIGHT_STANDING = f32(1.8)
HEIGHT_CROUCHING = f32(1.5)
MIN_HORIZONTAL_SQR = 9.0e-6
MIN_VERTICAL = 0.003


def movement_speed(sprinting: bool) -> float:
    """Movement-speed attribute (base plus sprint modifier), stored as a float."""
    v = BASE_SPEED
    if sprinting:
        v = v * (1.0 + SPRINT_MULTIPLIER)
    return f32(v)


def apply_threshold(p) -> None:
    """Zero velocity components that are too small to matter."""
    if p.vx * p.vx + p.vz * p.vz < MIN_HORIZONTAL_SQR:
        p.vx = 0.0
        p.vz = 0.0
    if abs(p.vy) < MIN_VERTICAL:
        p.vy = 0.0


def jump_from_ground(p) -> None:
    p.vy = max(JUMP_POWER, p.vy)
    if p.sprinting:
        r = fmul(p.yaw, DEG_TO_RAD_F)
        p.vx += -mth_sin(r) * SPRINT_JUMP_BOOST
        p.vz += mth_cos(r) * SPRINT_JUMP_BOOST


def acceleration(p, friction: float) -> float:
    if p.on_ground:
        return fmul(p.speed, fdiv(GROUND_ACCEL, fmul(fmul(friction, friction), friction)))
    return AIR_SPEED_SPRINTING if p.sprinting else AIR_SPEED


def input_vector(xxa: float, zza: float, speed: float, yaw: float):
    """Rotate the (strafe, forward) input by yaw and scale by speed; returns (dx, dz)."""
    x, z = xxa, zza
    lsq = x * x + z * z
    if lsq < 1.0e-7:
        return 0.0, 0.0
    if lsq > 1.0:
        n = math.sqrt(lsq)
        x, z = x / n, z / n
    x, z = x * speed, z * speed
    r = fmul(yaw, DEG_TO_RAD_F)
    s, c = mth_sin(r), mth_cos(r)
    return x * c - z * s, z * c + x * s


MINOR_COLLISION_ANGLE = 0.13962633907794952  # about 8 degrees
MINOR_EPS = 9.999999747378752e-06


def collision_is_minor(p, mx: float, mz: float) -> bool:
    """A wall hit is 'minor' when the actual movement stays within ~8 degrees of the input direction."""
    r = fmul(p.yaw, DEG_TO_RAD_F)
    s, c = mth_sin(r), mth_cos(r)
    gx = p.xxa * c - p.zza * s
    gz = p.zza * c + p.xxa * s
    want = gx * gx + gz * gz
    got = mx * mx + mz * mz
    if want < MINOR_EPS or got < MINOR_EPS:
        return False
    cosang = (gx * mx + gz * mz) / math.sqrt(want * got)
    if not -1.0 <= cosang <= 1.0:
        return False  # acos would be NaN in Java; NaN < x is false
    return math.acos(cosang) < MINOR_COLLISION_ANGLE


def move(p, world) -> None:
    """Move by the current velocity with collision; update flags and zero blocked components."""
    mx, my, mz = p.vx, p.vy, p.vz
    height = HEIGHT_CROUCHING if p.pose == "CROUCHING" else HEIGHT_STANDING
    box = collision.make_box(p.x, p.y, p.z, HALF_WIDTH, height)
    cx, cy, cz = collision.collide(box, (mx, my, mz), world.boxes)
    p.x, p.y, p.z = p.x + cx, p.y + cy, p.z + cz
    hit_x = abs(cx - mx) >= 1.0e-5
    hit_z = abs(cz - mz) >= 1.0e-5
    vertical = my != cy
    p.horizontal_collision = hit_x or hit_z
    p.minor_horizontal_collision = p.horizontal_collision and collision_is_minor(p, cx, cz)
    p.on_ground = vertical and my < 0.0
    if hit_x:
        p.vx = 0.0
    if hit_z:
        p.vz = 0.0
    if vertical:
        p.vy = 0.0


def travel(p, world, xxa: float, zza: float) -> None:
    friction = world.friction_below(p.x, p.y, p.z) if p.on_ground else 1.0
    keep = fmul(friction, AIR_FRICTION)
    dx, dz = input_vector(xxa, zza, acceleration(p, friction), p.yaw)
    p.vx += dx
    p.vz += dz
    move(p, world)
    vy = p.vy - GRAVITY
    p.vx = p.vx * keep
    p.vy = vy * VERTICAL_DRAG
    p.vz = p.vz * keep
