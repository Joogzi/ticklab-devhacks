"""Dev tool (harness-private): generate the seeded-bug cases from the pristine sim.

Each case gets bugs/<id>/{case.json, bug.patch, fix.patch, [trap.patch], hidden/*.json}.
bug.patch: pristine -> buggy. fix.patch: buggy -> pristine (reference fix). trap.patch: buggy -> plausible wrong fix.
Run: python bugs/build_bugs.py   (then: python -m factory bugs check)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from factory import patchutil, scenarios, util  # noqa: E402

PHYS, PLAYER, INPUT = "sim/src/mcsim/physics.py", "sim/src/mcsim/player.py", "sim/src/mcsim/input.py"


def K(key, at, down=True):
    return {"at": at, "key": key, "down": down}


def hold(key, a, b):
    return [K(key, a), K(key, b, False)]


def S(name, dur, *groups):
    acts = sorted([x for g in groups for x in (g if isinstance(g, list) else [g])], key=lambda a: a["at"])
    return scenarios.make(name, dur, acts)


def look(at, yaw, pitch=0):
    return {"at": at, "yaw": yaw, "pitch": pitch}


# ----------------------------------------------------------------------------- edits (exact text)
E_B1 = [(PHYS, "    if p.sprinting:\n        r = fmul(p.yaw", "    if p.sprinting and not p.on_ground:\n        r = fmul(p.yaw")]
T_B1 = [(PHYS, "    if p.sprinting and not p.on_ground:\n", "    if p.on_ground:\n")]

_SPRINT_OK = """        self.crouching = self.last_keys.shift
        move = inp.move_vector(keys)
        self.last_keys = keys.copy()
        forward = move[1] > 1.0e-5
        if not self.sprinting and forward and not self.crouching and keys.sprint:
            self.sprinting = True
        if self.sprinting and (not forward or (self.horizontal_collision and not self.minor_horizontal_collision)):
            self.sprinting = False
"""
_SPRINT_BUG = """        self.crouching = self.last_keys.shift
        was_forward = inp.move_vector(self.last_keys)[1] > 1.0e-5
        move = inp.move_vector(keys)
        self.last_keys = keys.copy()
        forward = move[1] > 1.0e-5
        if self.sprinting and (not was_forward or (self.horizontal_collision and not self.minor_horizontal_collision)):
            self.sprinting = False
        if not self.sprinting and forward and not self.crouching and keys.sprint:
            self.sprinting = True
"""
E_B2 = [(PLAYER, _SPRINT_OK, _SPRINT_BUG)]
T_B2 = [(PLAYER, """        if self.sprinting and (not was_forward or (self.horizontal_collision and not self.minor_horizontal_collision)):
            self.sprinting = False
        if not self.sprinting and forward and not self.crouching and keys.sprint:
            self.sprinting = True
""", """        if not self.sprinting and forward and not self.crouching and keys.sprint:
            self.sprinting = True
        if self.sprinting and (not forward or not keys.sprint or (self.horizontal_collision and not self.minor_horizontal_collision)):
            self.sprinting = False
""")]

E_B3 = [(PLAYER, "        if self.no_jump_delay > 0:\n", "        if self.no_jump_delay > 0 and self.on_ground:\n")]

E_B4 = [(PHYS, "    vy = p.vy - GRAVITY\n    p.vx = p.vx * keep\n    p.vy = vy * VERTICAL_DRAG\n",
         "    vy = p.vy * VERTICAL_DRAG\n    p.vx = p.vx * keep\n    p.vy = vy - GRAVITY\n")]

E_B5 = [(INPUT, '''def _to_unit_square(v):
    n = _length(v[0], v[1])
    if n <= 0.0:
        return v
    u = _scale(v, fdiv(1.0, n))
    ax, ay = abs(u[0]), abs(u[1])
    r = fdiv(ax, ay) if ay > ax else fdiv(ay, ax)
    k = fsqrt(f32(1.0 + fmul(r, r)))
    return _scale(u, min(fmul(n, k), 1.0))
''', '''def _clamp_length(v):
    n = _length(v[0], v[1])
    if n > 1.0:
        return _scale(v, fdiv(1.0, n))
    return v
'''), (INPUT, "sneak slowdown, then map the circle onto the unit square.", "sneak slowdown, then clamp to unit length."),
        (INPUT, "    return _to_unit_square(v)\n", "    return _clamp_length(v)\n")]
T_B5 = [(INPUT, "    if n > 1.0:\n        return _scale(v, fdiv(1.0, n))", "    if n > 0.0:\n        return _scale(v, fdiv(1.0, n))")]

_ACC_OK = """def acceleration(p, friction: float) -> float:
    if p.on_ground:
        return fmul(p.speed, fdiv(GROUND_ACCEL, fmul(fmul(friction, friction), friction)))
    return AIR_SPEED_SPRINTING if p.sprinting else AIR_SPEED
"""
_ACC_BUG = """def acceleration(p, friction: float) -> float:
    return fmul(p.speed, fdiv(GROUND_ACCEL, fmul(fmul(friction, friction), friction)))
"""
E_B6 = [(PHYS, "AIR_SPEED = f32(0.02)\nAIR_SPEED_SPRINTING = f32(0.025999999)\n", ""), (PHYS, _ACC_OK, _ACC_BUG)]
T_B6 = [(PHYS, _ACC_BUG, """def acceleration(p, friction: float) -> float:
    if p.on_ground:
        return fmul(p.speed, fdiv(GROUND_ACCEL, fmul(fmul(friction, friction), friction)))
    return f32(0.02)
""")]

E_B7 = [(PHYS, "MIN_HORIZONTAL_SQR = 9.0e-6\nMIN_VERTICAL = 0.003\n", "MIN_SPEED = 0.003\n"),
        (PHYS, """    if p.vx * p.vx + p.vz * p.vz < MIN_HORIZONTAL_SQR:
        p.vx = 0.0
        p.vz = 0.0
    if abs(p.vy) < MIN_VERTICAL:
""", """    if abs(p.vx) < MIN_SPEED:
        p.vx = 0.0
    if abs(p.vz) < MIN_SPEED:
        p.vz = 0.0
    if abs(p.vy) < MIN_SPEED:
""")]

E_B8 = [(PHYS, """    keep = fmul(friction, AIR_FRICTION)
    dx, dz = input_vector(xxa, zza, acceleration(p, friction), p.yaw)
    p.vx += dx
    p.vz += dz
    move(p, world)
""", """    dx, dz = input_vector(xxa, zza, acceleration(p, friction), p.yaw)
    p.vx += dx
    p.vz += dz
    move(p, world)
    keep = fmul(world.friction_below(p.x, p.y, p.z) if p.on_ground else 1.0, AIR_FRICTION)
""")]

# ----------------------------------------------------------------------------- hidden reference variants
H_SPRINT_JUMP = [S("h_sj_early", 45, hold("forward", 0, 30), hold("sprint", 0, 30), hold("jump", 5, 6)),
                 S("h_sj_yaw45", 50, look(0, 45), hold("forward", 0, 30), hold("sprint", 0, 30), hold("jump", 12, 13)),
                 S("h_sj_yaw_m120", 50, look(0, -120), hold("forward", 0, 28), hold("sprint", 0, 28), hold("jump", 9, 10)),
                 S("h_walk_jump_late", 50, hold("forward", 0, 30), hold("jump", 18, 19)),
                 S("h_strafe_jump", 45, hold("left", 0, 25), hold("jump", 6, 7)),
                 S("h_sj_twice", 60, hold("forward", 0, 40), hold("sprint", 0, 40), hold("jump", 5, 6), hold("jump", 22, 23))]
H_SPRINT_STOP = [S("h_ss_fwd7", 40, hold("forward", 0, 7), hold("sprint", 0, 20)),
                 S("h_ss_fwd18", 45, hold("forward", 0, 18), hold("sprint", 0, 18)),
                 S("h_ss_fwd25_yaw", 50, look(0, 30), hold("forward", 0, 25), hold("sprint", 2, 25)),
                 S("h_ss_sprint_key_early", 45, hold("forward", 0, 28), hold("sprint", 0, 6)),
                 S("h_ss_retap", 55, hold("forward", 0, 12), hold("sprint", 0, 40), hold("forward", 20, 32)),
                 S("h_ss_air", 50, hold("forward", 0, 13), hold("sprint", 0, 30), hold("jump", 10, 11))]
H_COOLDOWN = [S("h_cd_hold30", 50, hold("jump", 0, 30)), S("h_cd_hold50", 60, hold("jump", 4, 55)),
              S("h_cd_run_hold", 50, hold("forward", 0, 30), hold("jump", 3, 40)),
              S("h_cd_sprint_hold", 50, hold("forward", 0, 30), hold("sprint", 0, 30), hold("jump", 6, 45)),
              S("h_cd_tap_tap", 50, hold("jump", 1, 2), hold("jump", 14, 15), hold("jump", 27, 28)),
              S("h_cd_back_hold", 50, hold("backward", 0, 25), hold("jump", 2, 35))]
H_GRAVITY = [S("h_g_idle", 30), S("h_g_jump0", 30, hold("jump", 0, 1)), S("h_g_jump_late", 40, hold("jump", 20, 21)),
             S("h_g_run_jump", 40, hold("forward", 0, 20), hold("jump", 4, 5)),
             S("h_g_hold", 45, hold("jump", 1, 40)), S("h_g_sneak_jump", 35, hold("shift", 0, 30), hold("jump", 3, 4))]
H_DIAG = [S("h_d_back_right", 45, hold("backward", 0, 25), hold("right", 0, 25)),
          S("h_d_fwd_right_long", 50, hold("forward", 0, 35), hold("right", 0, 35)),
          S("h_d_sneak_fr", 45, hold("shift", 0, 30), hold("forward", 0, 30), hold("right", 0, 30)),
          S("h_d_sneak_straight", 45, hold("shift", 0, 30), hold("backward", 0, 30)),
          S("h_d_switch", 50, hold("forward", 0, 30), hold("left", 10, 20)),
          S("h_d_yaw", 45, look(0, 135), hold("forward", 0, 25), hold("left", 0, 25))]
H_AIR = [S("h_a_walk_jump", 40, hold("forward", 0, 25), hold("jump", 5, 6)),
         S("h_a_sprint_jump", 45, hold("forward", 0, 30), hold("sprint", 0, 30), hold("jump", 7, 8)),
         S("h_a_strafe_jump", 40, hold("right", 0, 25), hold("jump", 4, 5)),
         S("h_a_diag_sprint_jump", 45, hold("forward", 0, 30), hold("left", 0, 30), hold("sprint", 0, 30), hold("jump", 9, 10)),
         S("h_a_late_input", 40, hold("jump", 2, 3), hold("forward", 5, 25)),
         S("h_a_back_jump", 40, hold("backward", 0, 20), hold("jump", 3, 4))]
H_THRESH = [S("h_t_diag_short", 35, hold("forward", 0, 6), hold("left", 0, 6)),
            S("h_t_diag_mid", 40, hold("forward", 0, 15), hold("right", 0, 15)),
            S("h_t_back_diag", 40, hold("backward", 0, 12), hold("right", 0, 12)),
            S("h_t_yaw30", 40, look(0, 30), hold("forward", 0, 12)),
            S("h_t_yaw_m45", 40, look(0, -45), hold("forward", 0, 18)),
            S("h_t_sneak_diag", 45, hold("shift", 0, 30), hold("forward", 0, 20), hold("left", 0, 20))]
H_FRICTION = [S("h_f_run_jump", 45, hold("forward", 0, 30), hold("jump", 6, 7)),
              S("h_f_strafe_jump", 40, hold("left", 0, 20), hold("jump", 8, 9)),
              S("h_f_back_jump", 45, hold("backward", 0, 25), hold("jump", 12, 13)),
              S("h_f_sprint_jump", 45, hold("forward", 0, 30), hold("sprint", 0, 30), hold("jump", 15, 16)),
              S("h_f_release_air", 40, hold("forward", 0, 8), hold("jump", 5, 6)),
              S("h_f_diag_jump", 45, hold("forward", 0, 30), hold("right", 0, 30), hold("jump", 10, 11))]

def SW(name, dur, *groups):
    """Hidden variant on the wall_v1 fixture."""
    return dict(S(name, dur, *groups), fixture="wall_v1")


_STOP_OK = "        if self.sprinting and (not forward or (self.horizontal_collision and not self.minor_horizontal_collision)):\n"
E_B10 = [(PLAYER, _STOP_OK, "        if self.sprinting and (not forward or self.horizontal_collision):\n")]
T_B10 = [(PLAYER, "        if self.sprinting and (not forward or self.horizontal_collision):\n", "        if self.sprinting and not forward:\n")]
E_B11 = [(PHYS, "    if hit_x:\n        p.vx = 0.0\n    if hit_z:\n        p.vz = 0.0\n",
          "    if hit_x and p.on_ground:\n        p.vx = 0.0\n    if hit_z and p.on_ground:\n        p.vz = 0.0\n")]
T_B11 = [(PHYS, "    if hit_x and p.on_ground:\n        p.vx = 0.0\n    if hit_z and p.on_ground:\n        p.vz = 0.0\n",
          "    if hit_x and p.on_ground:\n        p.vx = 0.0\n    if hit_z and (p.on_ground or p.sprinting):\n        p.vz = 0.0\n")]
H_WALL_SPRINT = [SW("h_w_glance_80", 55, hold("forward", 0, 18), look(20, 80), hold("forward", 20, 50), hold("sprint", 20, 50)),
                 SW("h_w_glance_m84", 55, hold("forward", 0, 18), look(20, -84), hold("forward", 20, 50), hold("sprint", 20, 50)),
                 SW("h_w_steep_45", 55, hold("forward", 0, 18), look(20, 45), hold("forward", 20, 50), hold("sprint", 20, 50)),
                 SW("h_w_sprint_into_late", 45, hold("forward", 0, 35), hold("sprint", 4, 35)),
                 SW("h_w_diag_sprint_r", 45, hold("forward", 0, 35), hold("right", 0, 35), hold("sprint", 0, 35)),
                 SW("h_w_glance_jump", 55, hold("forward", 0, 18), look(20, 84), hold("forward", 20, 50), hold("sprint", 20, 50), hold("jump", 30, 31))]
H_WALL_AIR = [SW("h_w_jump_into_early", 45, hold("forward", 0, 35), hold("sprint", 0, 35), hold("jump", 4, 5)),
              SW("h_w_walk_jump_into", 45, hold("forward", 0, 35), hold("jump", 8, 9)),
              SW("h_w_land_then_jump", 55, hold("forward", 0, 45), hold("sprint", 0, 45), hold("jump", 24, 25)),
              SW("h_w_diag_jump_slide", 45, hold("forward", 0, 35), hold("left", 0, 35), hold("jump", 12, 13)),
              SW("h_w_hold_jump_wall", 55, hold("forward", 0, 45), hold("jump", 16, 45)),
              SW("h_w_back_jump_off", 50, hold("forward", 0, 20), hold("backward", 24, 40), hold("jump", 26, 27))]

CASES = [
    {"id": "b1_sprint_jump_boost", "name": "Sprint-jump boost missing", "families": ["jump", "sprint"],
     "plausible": False, "edits": E_B1, "trap": T_B1, "trap_note": "boost on every jump (also walking jumps)",
     "repro": ["diag_sprint_jump_fr"], "hidden": H_SPRINT_JUMP,
     "report": "Sprint-jumping feels broken. If I hold W and sprint and then jump once on flat ground, I land "
               "about where a normal running jump lands. In the real game a sprint-jump gives you an extra push "
               "forward at takeoff and you clearly go farther."},
    {"id": "b2_sprint_stop_late", "name": "Sprint stops one tick late", "families": ["sprint"],
     "plausible": True, "edits": E_B2, "trap": T_B2, "trap_note": "also stops sprinting when the sprint key is released",
     "repro": ["sprint_run"], "hidden": H_SPRINT_STOP,
     "report": "When I let go of W while sprinting, the character keeps sprinting slightly too long. It's subtle, "
               "maybe a single tick, but our stopping distance after a sprint is a little longer than in recordings "
               "of the real game."},
    {"id": "b3_jump_cooldown", "name": "Jump cooldown frozen in the air", "families": ["jump"],
     "plausible": True, "edits": E_B3, "trap": None, "repro": ["jump_hold"], "hidden": H_COOLDOWN,
     "report": "Holding the jump key to hop repeatedly is way slower than vanilla. In the real game you hop again "
               "the moment you land; ours sits on the ground for a while before the next hop."},
    {"id": "b4_gravity_drag_order", "name": "Gravity and drag applied in the wrong order", "families": ["jump", "walk"],
     "plausible": True, "edits": E_B4, "trap": None, "repro": ["jump_stand"], "hidden": H_GRAVITY,
     "report": "Vertical motion is slightly off. Even standing still, our vertical velocity readout doesn't match "
               "the value the real client shows, and jump arcs look very slightly different from vanilla."},
    {"id": "b5_diagonal_input", "name": "Diagonal input mapped to the unit circle instead of the unit square",
     "families": ["diagonal", "sneak"], "plausible": True, "edits": E_B5, "trap": T_B5,
     "trap_note": "always normalize the input to length 1", "repro": ["diag_walk_fl"], "hidden": H_DIAG,
     "report": "Walking diagonally (W+A or W+D) is slower than in vanilla. In the real game diagonal walking "
               "covers ground a bit faster than ours does."},
    {"id": "b6_air_acceleration", "name": "Air acceleration uses the ground formula", "families": ["jump"],
     "plausible": True, "edits": E_B6, "trap": T_B6, "trap_note": "use 0.02 in the air even while sprinting",
     "repro": ["jump_run"], "hidden": H_AIR,
     "report": "Mid-air steering seems a bit too strong compared to the real game. Running jumps travel slightly too "
               "far, most noticeably when you keep holding W through the jump."},
    {"id": "b7_stop_threshold", "name": "Tiny-velocity cutoff applied per axis", "families": ["diagonal", "look"],
     "plausible": True, "edits": E_B7, "trap": None, "repro": ["diag_walk_fl"], "hidden": H_THRESH,
     "report": "When I stop after moving diagonally, the player comes to rest a tiny bit early compared to the real "
               "game. Straight-line stops look fine to me."},
    {"id": "b8_air_friction_timing", "name": "Drag uses the post-move ground state", "families": ["jump", "strafe"],
     "plausible": True, "edits": E_B8, "trap": None, "repro": ["jump_run"], "hidden": H_FRICTION,
     "report": "Running jumps: the takeoff and the landing both feel slightly wrong. Horizontal speed right after "
               "leaving the ground and right after touching down doesn't match vanilla recordings. Plain walking "
               "on the ground is fine."},
    {"id": "c9_compound_sprint_jump", "name": "Compound: sprint-jump boost missing + air acceleration formula",
     "families": ["jump", "sprint"], "plausible": True, "edits": E_B1 + E_B6, "trap": None, "components": ["b1_sprint_jump_boost", "b6_air_acceleration"],
     "repro": ["diag_sprint_jump_fr"], "hidden": H_SPRINT_JUMP + H_AIR,
     "report": "Sprint-jumping is off."},
    {"id": "b10_wall_glance_sprint", "name": "Any wall contact cancels sprint", "families": ["wall", "sprint"],
     "plausible": True, "edits": E_B10, "trap": T_B10, "trap_note": "never let a wall stop sprinting",
     "repro": ["wall_glance_sprint"], "hidden": H_WALL_SPRINT,
     "report": "If I sprint along a wall at a shallow angle, our character drops out of sprint the moment it brushes the "
               "wall. In the real game you keep sprinting while you skim along it."},
    {"id": "b11_wall_air_velocity", "name": "Wall hits in the air keep the blocked velocity", "families": ["wall", "jump"],
     "plausible": True, "edits": E_B11, "trap": None,
     "repro": ["wall_sprint_jump_land"], "hidden": H_WALL_AIR,
     "report": "Sprint-jumping after landing against a wall gives the player the wrong velocity."},
]


def edit(files: dict, edits) -> dict:
    out = dict(files)
    for path, old, new in edits:
        if out[path].count(old) != 1:
            raise SystemExit(f"edit target not unique/absent in {path}: {old[:60]!r} (count {out[path].count(old)})")
        out[path] = out[path].replace(old, new)
    return out


def diff(a: dict, b: dict) -> str:
    return "".join(patchutil.make(a[p], b[p], p) for p in sorted(a) if a[p] != b[p])


def build() -> list[str]:
    pristine = {p: (ROOT / p).read_text(encoding="utf-8") for p in (PHYS, PLAYER, INPUT)}
    ids = []
    for c in CASES:
        d = ROOT / "bugs" / c["id"]
        util.rmtree(d)
        (d / "hidden").mkdir(parents=True)
        buggy = edit(pristine, c["edits"])
        util.write_text(d / "bug.patch", diff(pristine, buggy))
        util.write_text(d / "fix.patch", diff(buggy, pristine))
        if c.get("trap"):
            util.write_text(d / "trap.patch", diff(buggy, edit(buggy, c["trap"])))
        for s in c["hidden"]:
            assert not scenarios.validate(s), (s["name"], scenarios.validate(s))
            util.write_json(d / "hidden" / f"{s['name']}.json", s)
        meta = {k: c[k] for k in ("id", "name", "families", "report", "plausible", "repro") if k in c}
        meta["repro_scenarios"] = meta.pop("repro")
        meta["trap"] = bool(c.get("trap"))
        meta["trap_note"] = c.get("trap_note")
        meta["components"] = c.get("components", [c["id"]])
        meta["hidden_variants"] = [s["name"] for s in c["hidden"]]
        util.write_json(d / "case.json", meta)
        ids.append(c["id"])
    util.write_json(ROOT / "bugs" / "cases.json", {"schema_version": 1, "cases": ids})
    return ids


if __name__ == "__main__":
    print("built:", ", ".join(build()))
