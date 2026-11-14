"""Visible unit tests for mcsim (run: python -m unittest discover -s tests, with PYTHONPATH=src)."""
import unittest

from mcsim.main import simulate


def scen(name, duration, actions):
    return {"schema_version": 1, "name": name, "duration": duration, "fixture": "flat_stone_v1", "actions": actions}


def press(key, at, release=None):
    acts = [{"at": at, "key": key, "down": True}]
    if release is not None:
        acts.append({"at": release, "key": key, "down": False})
    return acts


def run(s):
    tr = simulate(s)
    return tr[0], tr[1:]


class TraceFormat(unittest.TestCase):
    def test_header_and_one_record_per_tick(self):
        head, recs = run(scen("idle", 20, []))
        self.assertEqual(head["schema"], "ticklab.trace/1")
        self.assertEqual([r["tick"] for r in recs], list(range(20)))
        for f in ("x", "y", "z", "vx", "vy", "vz", "on_ground", "yaw", "pitch", "pose"):
            self.assertIn(f, recs[0])

    def test_deterministic(self):
        s = scen("mix", 40, press("forward", 0, 30) + press("jump", 5, 6))
        self.assertEqual(simulate(s), simulate(s))


class Idle(unittest.TestCase):
    def test_idle_stays_on_floor(self):
        _, recs = run(scen("idle", 30, []))
        for r in recs:
            self.assertTrue(r["on_ground"])
            self.assertAlmostEqual(r["y"], 100.0, places=9)
            self.assertEqual((r["x"], r["z"]), (0.5, 0.5))


class Walking(unittest.TestCase):
    def test_walk_forward_moves_plus_z(self):
        _, recs = run(scen("walk", 30, press("forward", 0, 20)))
        self.assertGreater(recs[19]["z"], 3.5)
        self.assertLess(recs[19]["z"], 5.5)
        self.assertAlmostEqual(recs[-1]["x"], 0.5, places=9)
        self.assertTrue(all(r["on_ground"] for r in recs))

    def test_walk_comes_to_rest(self):
        _, recs = run(scen("walk", 50, press("forward", 0, 10)))
        self.assertEqual(recs[-1]["vz"], 0.0)

    def test_strafe_left_moves_plus_x(self):
        _, recs = run(scen("left", 20, press("left", 0, 15)))
        self.assertGreater(recs[-1]["x"], 2.0)

    def test_sprint_is_faster(self):
        _, walk = run(scen("w", 30, press("forward", 0)))
        _, sprint = run(scen("s", 30, press("forward", 0) + press("sprint", 0)))
        self.assertGreater(sprint[-1]["z"], walk[-1]["z"] * 1.2)

    def test_sneak_is_slower(self):
        _, walk = run(scen("w", 30, press("forward", 0)))
        _, sneak = run(scen("s", 30, press("shift", 0) + press("forward", 0)))
        self.assertLess(sneak[-1]["z"] - 0.5, (walk[-1]["z"] - 0.5) * 0.5)


class Jumping(unittest.TestCase):
    def test_jump_apex_and_landing(self):
        _, recs = run(scen("jump", 30, press("jump", 0, 1)))
        apex = max(r["y"] for r in recs) - 100.0
        self.assertGreater(apex, 1.2)
        self.assertLess(apex, 1.3)
        self.assertFalse(recs[0]["on_ground"])
        self.assertTrue(recs[-1]["on_ground"])
        self.assertAlmostEqual(recs[-1]["y"], 100.0, places=9)


if __name__ == "__main__":
    unittest.main()
