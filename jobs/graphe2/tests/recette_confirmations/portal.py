"""Double MCP de recette : deux onglets de portail avec états distincts."""

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
active = 1
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    reply = {}
    if request["method"] == "tools/call":
        tool = request["params"]["name"]
        args = request["params"]["arguments"]
        active = args.get("tabId", active)
        name = chr(64 + active)
        success = (root / (name + ".verified")).exists()
        url = "https://portail.invalid/" + name + ("/actif" if success else "/attente")
        data = (
            {"activeTabId": active, "url": url}
            if tool == "page_switchTab"
            else {
                "text": "Espace "
                + name
                + (" actif candidat@example.invalid" if success else " en attente")
            }
        )
        reply = {"structuredContent": data}
    print(
        json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": reply}), flush=True
    )
