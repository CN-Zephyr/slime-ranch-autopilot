"""冒烟测试：验证插件契约与自动化核心的核心行为是否正确。

运行（无需安装任何第三方库）：
  python -m unittest discover -s tests
"""
from __future__ import annotations
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from plugin_check import load_manifest  # noqa: E402  (见下方 plugin_check.py)

MANIFEST = load_manifest()
from core.ranch import decide_build_action, facility_cost, RanchState, MAX_LEVEL  # noqa: E402
from core.sim import SimController  # noqa: E402
from core.comms import Comms  # noqa: E402
from core.game import run_manual_command  # noqa: E402
from core.explore import decide_explore_area, pick_new_slime  # noqa: E402


class ManifestTests(unittest.TestCase):
    def test_identity_lock(self):
        self.assertEqual(MANIFEST["plugin"]["id"], "slime_ranch_autopilot")
        main_map = MANIFEST["plugin"]["entry"].split(":")
        self.assertEqual(main_map[0], f"plugin.plugins.{MANIFEST['plugin']['id']}")
        self.assertTrue(main_map[1].endswith("Plugin"))
        self.assertEqual(MANIFEST["slime_ranch"]["default_mode"], "watch")

    def test_runtime_booleans(self):
        rt = MANIFEST["plugin_runtime"]
        self.assertIsInstance(rt["enabled"], bool)
        self.assertIsInstance(rt["auto_start"], bool)
        self.assertTrue(0 < rt["timeout"] <= 300)

    def test_ui_panel(self):
        ui_panels = MANIFEST["plugin"]["ui"]["panel"]
        self.assertTrue(any(p["entry"].endswith(".tsx") for p in ui_panels))

    def test_config_section(self):
        self.assertTrue(MANIFEST.get("slime_ranch", {}).get("timeout_seconds", 0) > 0)


class RanchLogicTests(unittest.TestCase):
    def test_2x_gate_blocks_when_not_enough(self):
        st = RanchState()
        self.assertIsNone(decide_build_action(st, funds=400))
        act = decide_build_action(st, funds=450)
        self.assertEqual(act, {"mode": "build", "kind": "corral", "cost": 225})

    def test_costs(self):
        self.assertEqual(facility_cost("corral", 1), 225)
        self.assertEqual(facility_cost("coop", 2), 650)

    def test_priorities_corral_then_garden_for_food_then_coop(self):
        st = RanchState()
        self.assertEqual(decide_build_action(st, 450)["kind"], "corral")
        st.level["corral"] = 1
        # 有围栏(有史莱姆要喂)但没菜园：食物闭环优先建菜园
        self.assertEqual(decide_build_action(st, 800)["kind"], "garden")
        st.level["garden"] = 1
        self.assertEqual(decide_build_action(st, 800)["kind"], "coop")
        st.level["coop"] = 1
        # 都建齐后进入升级阶段（每种只买一件升级）
        act = decide_build_action(st, 10000)
        self.assertEqual(act["mode"], "upgrade")
        self.assertEqual(act["kind"], "corral")
        st.upgrades["corral"] = ["NETTING"]
        st.level["corral"] = 2
        act = decide_build_action(st, 10000)
        self.assertEqual(act["kind"], "coop")


class SimTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.c = Comms(self.tmp)
        self.sim = SimController(self.c, start_funds=800)

    def test_build_consumes_funds(self):
        self.sim.build("corral")
        self.assertEqual(self.sim.funds, 575)
        self.assertEqual(self.sim.facilities["corral"], 1)

    def test_explore_catches_and_dedups(self):
        res1 = self.sim.explore()
        first = res1.get("caught")
        seen = {first}
        for _ in range(6):
            res = self.sim.explore()
            if res.get("caught"):
                seen.add(res["caught"])
        # 抓到至少 2 种且存在不重复
        self.assertGreaterEqual(len(seen), 2)

    def test_explore_all_areas_eventually(self):
        for _ in range(20):
            self.sim.explore()
        self.assertGreaterEqual(len(self.sim.areas_explored), 5)

    def test_sell_clears_and_adds_funds(self):
        self.sim.slimes.append("粉红史莱姆")
        self.sim.harvest()
        before = self.sim.funds
        r = self.sim.sell()
        self.assertTrue(r["ok"])
        self.assertEqual(self.sim.inventory, {})
        self.assertGreater(self.sim.funds, before)

    def test_sim_reports_discovery_lines(self):
        # 抓一只新史莱姆并通过 comms 汇报
        res = self.sim.explore()
        if res.get("caught"):
            self.c.report_discovery("slime-" + res["caught"], "抓到" + res["caught"])
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "outbox.jsonl")))


class CommandTests(unittest.TestCase):
    def test_chinese_command_mapping(self):
        r = run_manual_command(SimController(Comms(tempfile.mkdtemp())), "建造菜园")
        self.assertTrue(r["ok"])
        self.assertIn("garden", r["note"])


if __name__ == "__main__":
    unittest.main(verbosity=2)