from app.scanner.scorer import score_state

class Scanner:
    def __init__(self, engine):
        self.engine = engine

    def snapshot(self):
        results = []
        for symbol, state in self.engine.states.items():
            result = score_state(state)
            results.append({
                "symbol": symbol,
                "score": result.score,
                "reasons": result.reasons,
                "price": state.last_price,
            })
        return sorted(results, key=lambda x: x["score"], reverse=True)
