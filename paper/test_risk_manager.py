import sys
from pathlib import Path
PROJECT_ROOT=Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0,str(PROJECT_ROOT))
from app.paper.risk_manager import PaperRiskManager

def main():
    r=PaperRiskManager(max_risk_per_trade_pct=0.5,max_daily_loss_pct=2,max_open_positions=2,max_total_exposure_pct=50,max_position_pct=10)
    d=r.evaluate(equity=1000,open_positions=0,current_exposure=0,stop_distance_pct=1.5,requested_allocation=50)
    assert d.allowed and d.allocation_usdt <= 50
    r.record_closed_pnl(-25)
    d2=r.evaluate(equity=1000,open_positions=0,current_exposure=0,stop_distance_pct=1.5,requested_allocation=50)
    assert not d2.allowed
    print('RISK MANAGER TEST PASSED')
if __name__=='__main__': main()
