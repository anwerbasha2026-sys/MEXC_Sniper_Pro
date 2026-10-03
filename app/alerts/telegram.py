from __future__ import annotations

import httpx


class TelegramAlerter:
    def __init__(
        self,
        token: str = "",
        chat_id: str = "",
    ):
        self.token = token.strip()
        self.chat_id = chat_id.strip()

    @property
    def enabled(self) -> bool:
        return bool(
            self.token
            and self.chat_id
        )

    async def send(
        self,
        text: str,
    ) -> bool:
        if not self.enabled:
            return False

        url = (
            "https://api.telegram.org/"
            f"bot{self.token}/sendMessage"
        )

        async with httpx.AsyncClient(
            timeout=10
        ) as client:
            response = await client.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )

            response.raise_for_status()

        return True
