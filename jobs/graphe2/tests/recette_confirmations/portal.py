"""Transport MCP du portail de recette. Le formulaire Chrome vérifie le témoin soumis."""

import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
playwright, chrome = sys.argv[2:]
active = 1
marker = None
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    reply = {}
    if request["method"] == "tools/call":
        tool = request["params"]["name"]
        args = request["params"]["arguments"]
        active = args.get("tabId", active)
        name = {1: "A", 2: "B"}.get(active, "inconnu")
        if active == 1 and (root / "old-tab").exists():
            name = "B"
        success_path = root / (name + ".verified")
        url = (
            "https://portail.invalid/"
            + name
            + ("/actif" if success_path.exists() else "/confirmation")
        )
        data = {}
        with (root / "actions.log").open("a") as log:
            print(
                name,
                tool
                if tool
                in {
                    "page_switchTab",
                    "page_fillInput",
                    "page_clickElement",
                    "page_extractText",
                }
                else "unexpected",
                file=log,
            )
        if tool == "page_switchTab":
            data = {"activeTabId": active, "url": url}
        elif tool == "page_extractText":
            data = {
                "text": "Espace "
                + name
                + (
                    " actif candidat@example.invalid"
                    if success_path.exists()
                    else " en attente"
                )
            }
        elif tool == "page_fillInput" and args["target"] == {"selector": "#code"}:
            marker = args["value"]
        elif (
            tool == "page_clickElement"
            and args["target"] == {"selector": "button[data-confirm-registration]"}
            and marker
        ):
            payload = {
                "space": name,
                "token": marker,
                "digest": (root / (name + ".digest")).read_text(),
            }
            result = subprocess.run(
                ["node", Path(__file__).with_name("verify.cjs")],
                input=json.dumps(payload) + "\n",
                text=True,
                env={
                    "PATH": os.environ["PATH"],
                    "HOME": str(root),
                    "PLAYWRIGHT": playwright,
                    "CHROME": chrome,
                },
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=35,
                check=False,
            )
            marker = None
            with (root / "actions.log").open("a") as log:
                print(
                    name,
                    "validated" if result.returncode == 0 else "rejected",
                    file=log,
                )
            if result.returncode == 0:
                success_path.touch()
        else:
            reply = {
                "isError": True,
                "content": [{"type": "text", "text": "Action inconnue"}],
            }
        if not reply:
            reply = {"structuredContent": data}
    print(
        json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": reply}), flush=True
    )
