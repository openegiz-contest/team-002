import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'qazmine'))
from model import Mine, route, path_length, weighted_grade, TARGET_GRADE, benchmark
from setup_twins import definitions

class TestModel(unittest.TestCase):
    def test_reroute(self):
        default = route('A','C',set())
        bypass = route('A','C',{'road-main'})
        self.assertIn('road-main',[r for r,_ in default])
        self.assertNotIn('road-main',[r for r,_ in bypass])
        self.assertGreater(path_length(bypass),path_length(default))

    def test_conservation(self):
        m = Mine()
        for i in range(1200):
            m.step(20)
            m.validate()
        self.assertGreater(m.delivered_t,0)
        self.assertGreater(m.ore_mined_t,0)
        self.assertGreater(m.feed_grade,0)
        self.assertLess(m.feed_grade,1.11)

    def test_scenarios_reversible(self):
        m=Mine()
        for scenario in ('road_closed','excavator_failure','crusher_reduced'):
            m.scenario(scenario,True)
            self.assertIn(scenario,m.active_scenarios())
            for _ in range(200):
                m.step(20)
                m.validate()
            m.scenario(scenario,False)
            self.assertNotIn(scenario,m.active_scenarios())
        self.assertEqual(m.crusher_factor,1)
        self.assertEqual(len(m.closed),0)

    def test_grade_mass_weighting(self):
        self.assertAlmostEqual(weighted_grade([(40,0.45),(40,1.10)]),0.775)

    def test_twin_ids_distinct(self):
        objs=definitions()
        self.assertGreaterEqual(len(objs),12)
        self.assertEqual(len(set(k for k,_ in objs)),len(objs))
        self.assertTrue(all(v['policyId']=='default:basic_policy' for _,v in objs))

    def test_benchmark_reproducible(self):
        x=benchmark(2)
        y=benchmark(2)
        self.assertEqual(x,y)
        self.assertGreater(x['adaptive']['tonnes'],0)
        self.assertGreater(x['basic']['tonnes'],0)

if __name__=='__main__': unittest.main()
