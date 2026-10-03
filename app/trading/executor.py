class Executor:
    def __init__(self, mode="PAPER"):
        self.mode = mode

    def submit(self, *args, **kwargs):
        if self.mode != "PAPER":
            raise RuntimeError(
                "Live execution is intentionally disabled in this scaffold. "
                "Implement and test authenticated MEXC Spot execution separately."
            )
        return {"status": "PAPER_ONLY"}
