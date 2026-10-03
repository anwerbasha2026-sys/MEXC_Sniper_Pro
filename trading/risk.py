class RiskManager:
    def __init__(self, max_risk_per_trade=0.005, max_daily_loss=0.02,
                 max_open_positions=3):
        self.max_risk_per_trade = max_risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_open_positions = max_open_positions

    def can_open(self, open_positions, daily_pnl, equity):
        if open_positions >= self.max_open_positions:
            return False
        if equity <= 0:
            return False
        if daily_pnl <= -(equity * self.max_daily_loss):
            return False
        return True
