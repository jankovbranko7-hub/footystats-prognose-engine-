import unittest
import v1_full_data_engine as v1

class GateV1Tests(unittest.TestCase):
    def result(self,key='btts_yes'): return {'strongest_market':{'key':key},'samples':{'security':'NIEDRIG'}}
    def protocol(self,conf,counters=None,strength=35):
        return {'confirming_blocks':conf,'counter_blocks':counters or [],'final_decision':'BEOBACHTEN','gates':{'probability_family_strength':{'strength_pct':strength},'multi_block_confirmation':{'required':4},'robustness':'BESTANDEN','data_quality':'HOCH','coherence':{'passed':True},'pre_match_integrity':{'strict_pre_match':True}}}
    def test_btts_3_of_3(self): self.assertEqual(v1.gate_v1(self.result(),self.protocol(['UNDERLYING','MATCH','FORM']))['final_decision'],'SPIELEN')
    def test_btts_2_of_3(self): self.assertEqual(v1.gate_v1(self.result(),self.protocol(['UNDERLYING','MATCH']))['final_decision'],'BEOBACHTEN')
    def test_1x2_stays_four(self): self.assertEqual(v1.gate_v1(self.result('home_win'),self.protocol(['UNDERLYING','MATCH','FORM']))['gate_v1']['v1_required'],4)
    def test_counter_still_blocks(self): self.assertEqual(v1.gate_v1(self.result(),self.protocol(['UNDERLYING','MATCH','FORM'],['FORM']))['final_decision'],'BEOBACHTEN')

class ExtractionTests(unittest.TestCase):
    def test_overall_table_preferred(self):
        d={'data':{'all_matches_table_away':[{'id':1,'position':1}],'all_matches_table_overall':[{'id':1,'position':7},{'id':2,'position':1}]}}
        self.assertEqual(v1._overall_table(d)[0]['position'],7)
    def test_trend_parser(self):
        t=v1._trend_side([['chart',"Team has picked up 7 points from the last 5 games. That's 1.4 points per game on average. BTTS has landed in an intriguing 5 of those games. Team has scored 7 times in the last 5 fixtures."]])
        self.assertEqual(t['last5_points'],7.0); self.assertEqual(t['last5_btts'],5.0)
    def test_player_detail_filters_competition(self):
        d={'players':[{'data':[{'id':1,'competition_id':10,'club_team_id':100,'position':'Forward','minutes_played_overall':900,'detailed':{'npxg_per_90_overall':0.5}},{'id':1,'competition_id':9,'club_team_id':100,'position':'Forward','minutes_played_overall':900,'detailed':{'npxg_per_90_overall':9.9}}]}]}
        rows=v1._pd_rows(d,100,10); self.assertEqual(len(rows),1); self.assertAlmostEqual(v1._pd_side(rows)['npxg_per90'],0.5)

if __name__=='__main__': unittest.main()
