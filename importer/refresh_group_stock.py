#!/usr/bin/env python3
"""Recalcula o estoque mensal após a importação completa dos microdados."""

import os
import requests

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not url or not key:
    raise RuntimeError("Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.")

response = requests.post(
    f"{url}/rest/v1/rpc/caged_group_recalculate_stock",
    headers={
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    },
    json={},
    timeout=360,
)
response.raise_for_status()
print("Estoque setorial mensal recalculado.")
