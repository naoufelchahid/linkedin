"""Client du vrai MCP. stdin/stdout transportent exclusivement les messages JSON-RPC."""

import asyncio
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

from linkedin_applications.browser import Browsentic
from linkedin_applications.codex import ConnectorError, Session
from portal import BASE, PDF


class PipeSession(Session):
    def __init__(self):
        super().__init__([], Path.cwd())

    async def write(self, message):
        print(json.dumps({"jsonrpc": "2.0", **message}), flush=True)

    async def read(self):
        data = sys.stdin.readline()
        if not data:
            raise ConnectorError("MCP déconnecté")
        return json.loads(data)


async def run(phase, nonce):
    rpc = PipeSession()
    browser = Browsentic("/tmp", [], {})
    await browser.connect(rpc)

    async def call(name, **arguments):
        result = await rpc.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise ConnectorError(f"{name}: {result['content'][0]['text'][:320]}")
        return browser.json_result(result)

    async def expect(text):
        for _ in range(20):
            result = await call("page_extractText")
            if text in result.get("text", "") or text in result.get("content", ""):
                return
            await asyncio.sleep(0.25)
        raise RuntimeError(
            f"Texte de recette absent dans la page. Résultat {result.get('content', '')[:120]!r}"
        )

    print(f"UID du worker Docker {os.getuid()}", file=sys.stderr)
    start = await call(
        "page_openTab", url=BASE + ("/start" if phase == "start" else "/resume")
    )
    if phase == "resume":
        await expect("Session de recette retrouvee")
        print("Cookie du portail retrouvé après redémarrage", file=sys.stderr)
        return

    visual_review = False
    try:
        await call("page_switchFrame", frame={"selector": "#cadre"})
        await expect("Lecture du cadre " + nonce)
        print("Texte de l’iframe vérifié", file=sys.stderr)
        await call("page_switchFrame")
    except ConnectorError as error:
        if not str(error).startswith("page_switchFrame: UNSUPPORTED"):
            raise
        print(error, file=sys.stderr)
        screen = await rpc.request(
            "tools/call", {"name": "page_screenshot", "arguments": {}}
        )
        saved = False
        for item in screen.get("content", []):
            if item["type"] == "image":
                path = Path("/preuve") / (
                    "cadre.jpg" if item["mimeType"] == "image/jpeg" else "cadre.png"
                )
                path.write_bytes(base64.b64decode(item["data"], validate=True))
                saved = True
        if not saved:
            raise RuntimeError("Capture du cadre indisponible")
        visual_review = True
        print(f"Capture du cadre à vérifier, valeur attendue {nonce}", file=sys.stderr)
    piece = await call("page_openTab", url=BASE + "/piece")
    if piece["tabId"] == start["tabId"]:
        raise RuntimeError("Le second onglet doit être distinct")
    if await browser.current_url(rpc, piece["tabId"]) != BASE + "/piece":
        raise RuntimeError("Onglet de recette inactif")
    print("Second onglet actif vérifié", file=sys.stderr)
    captured = await call("page_captureDownload", url=BASE + "/recette.pdf")
    await call(
        "page_attachFile",
        downloadId=captured["downloadId"],
        target={"selector": "#piece"},
    )
    await expect(hashlib.sha256(PDF.read_bytes()).hexdigest())
    print("SHA-256 du PDF lu depuis le champ de fichier vérifié", file=sys.stderr)
    return 2 if visual_review else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(run(*sys.argv[1:])))
    except ConnectorError as error:
        sys.exit(str(error))
