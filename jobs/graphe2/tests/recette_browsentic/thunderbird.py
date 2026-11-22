"""Recette du MCP Thunderbird dans un espace réseau dédié au loopback."""

import argparse
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from run import worker


def prepare(profile, xpi, nonce):
    extensions = profile / "extensions"
    extensions.mkdir(parents=True)
    shutil.copyfile(xpi, extensions / "thunderbird-mcp@tkasperczyk.dev.xpi")
    mail = profile / "Mail/Local Folders"
    mail.mkdir(parents=True)
    fixture = (
        "From: portail@example.invalid\r\nTo: candidat@example.invalid\r\n"
        f"Subject: Recette {nonce}\r\nMessage-ID: <{nonce}@example.invalid>\r\n"
        "Date: Sun, 22 Nov 2026 10:00:00 +0000\r\n\r\n"
        f"Confirmation locale {nonce}\r\n"
    )
    with zipfile.ZipFile(extensions / "fixture@example.invalid.xpi", "w") as addon:
        addon.writestr(
            "manifest.json",
            json.dumps(
                {
                    "manifest_version": 2,
                    "name": "Courriel de recette",
                    "version": "1.0",
                    "browser_specific_settings": {
                        "gecko": {"id": "fixture@example.invalid"}
                    },
                    "permissions": [
                        "accountsRead",
                        "accountsFolders",
                        "messagesRead",
                        "messagesImport",
                    ],
                    "background": {"scripts": ["seed.js"]},
                }
            ),
        )
        addon.writestr("fixture.eml", fixture)
        addon.writestr(
            "seed.js",
            """
            (async () => {
                const [local] = await browser.accounts.list();
                const dest = await browser.folders.create(local.rootFolder, "Recette");
                const blob = await (await fetch(browser.runtime.getURL("fixture.eml"))).blob();
                await browser.messages.import(new File([blob], "fixture.eml"), dest);
            })().catch(e => console.error("FIXTURE", e));
        """,
        )
    prefs = {
        "extensions.autoDisableScopes": 0,
        "extensions.enabledScopes": 15,
        "extensions.experiments.enabled": True,
        "mail.account.account1.server": "server1",
        "mail.accountmanager.accounts": "account1",
        "mail.accountmanager.localfoldersserver": "server1",
        "mail.server.server1.type": "none",
        "mail.server.server1.hostname": "Local Folders",
        "mail.server.server1.directory": str(mail),
        "mail.server.server1.name": "Local Folders",
        "mail.server.server1.userName": "nobody",
    }
    (profile / "user.js").write_text(
        "".join(
            f"user_pref({json.dumps(k)}, {json.dumps(v)});\n" for k, v in prefs.items()
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thunderbird", required=True, type=Path)
    parser.add_argument("--mcp-repo", required=True, type=Path)
    parser.add_argument("--image", default="linkedin-browsentic-recette")
    args = parser.parse_args()
    if {
        s.split(":")[0].strip()
        for s in Path("/proc/net/dev").read_text().splitlines()[2:]
    } != {"lo"}:
        raise RuntimeError("Exécuter la recette dans un réseau limité au loopback")
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        profile = root / "profil"
        nonce = secrets.token_hex(12)
        prepare(profile, args.mcp_repo / "dist/thunderbird-mcp.xpi", nonce)
        info = root / "thunderbird-mcp/connection.json"
        runtime = {k: os.environ[k] for k in ("PATH", "LANG") if k in os.environ}
        runtime.update(
            HOME=tmp,
            TMPDIR=tmp,
            MOZ_HEADLESS="1",
            DBUS_SESSION_BUS_ADDRESS="disabled:",
            THUNDERBIRD_MCP_CONNECTION_FILE=str(info),
        )
        with subprocess.Popen(
            [args.thunderbird, "-no-remote", "-profile", profile, "-offline"],
            env=runtime,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ) as thunderbird:
            try:
                for _ in range(90):
                    if info.exists():
                        break
                    if thunderbird.poll() is not None:
                        raise RuntimeError("Thunderbird a quitté avant son MCP")
                    time.sleep(1)
                else:
                    raise RuntimeError("Le MCP Thunderbird du profil ne répond pas")
                proof = root / "preuve"
                proof.mkdir()
                return worker(
                    "mail",
                    nonce,
                    args.image,
                    proof,
                    mcp_command=["node", args.mcp_repo / "mcp-bridge.cjs"],
                    mcp_env=runtime,
                )
            finally:
                thunderbird.terminate()
                try:
                    thunderbird.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    thunderbird.kill()


if __name__ == "__main__":
    raise SystemExit(main())
