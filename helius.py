from __future__ import annotations
import requests
from typing import Any, Dict, List, Optional

class HeliusClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base_url = "https://api-mainnet.helius-rpc.com"

    def get_transactions_by_address(
        self,
        address: str,
        before: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Helius Enhanced Transactions by address:
        GET /v0/addresses/{address}/transactions?api-key=...
        Docs: Helius 'Get Enhanced Transactions By Address'. :contentReference[oaicite:3]{index=3}
        """
        url = f"{self.base_url}/v0/addresses/{address}/transactions"
        params = {"api-key": self.api_key, "limit": limit}
        if before:
            params["before"] = before

        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        return data
