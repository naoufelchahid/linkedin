"""Recette Linux du worker Docker vers le Bridge et le navigateur sur l’hôte."""

import argparse
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import nullcontext
from pathlib import Path

from portal import portal

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def worker(phase, nonce, image, proof, *, mcp_command=None, mcp_env=None):
    name = f"recette-browsentic-{proof.parent.name}-{phase}"
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--pull=never",
        "--network=none",
        "--name",
        name,
        "-v",
        f"{proof}:/preuve",
        image,
        "python",
        "/recette/worker.py",
        phase,
        nonce,
    ]
    if phase in {"mail", "secret"}:
        command[2:2] = ["-v", f"{HERE}:/recette:ro"]
    # stdout est le transport RPC. Le pilote Docker le journaliserait en clair.
    sensitive = phase == "secret"
    if sensitive:
        command[2:2] = ["--log-driver=none"]
    log = (proof / "worker-mcp.log").open("wb") if sensitive else nullcontext()
    with (
        log as diagnostic,
        subprocess.Popen(
            mcp_command or ["browsentic", "mcp"],
            env=mcp_env,
            stderr=diagnostic,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        ) as mcp,
    ):
        try:
            return subprocess.run(
                command,
                stdin=mcp.stdout,
                stdout=mcp.stdin,
                stderr=diagnostic,
                timeout=None if phase == "pdf-panel" else 150,
                check=False,
            ).returncode
        except (KeyboardInterrupt, subprocess.TimeoutExpired):
            subprocess.run(
                ["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, check=False
            )
            raise
        finally:
            mcp.terminate()


def wait_for_cookie_commit(profile):
    # Chrome regroupe les écritures. Attendre l’enregistrement de la ligne synthétique
    # avant la fermeture du processus, sans lire la valeur du cookie.
    database = profile / "Default/Cookies"
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if database.exists():
            with sqlite3.connect(
                f"{database.as_uri()}?mode=ro", uri=True
            ) as connection:
                stored = connection.execute(
                    "SELECT 1 FROM cookies WHERE host_key=? AND name=? AND is_persistent=1",
                    ("127.0.0.1", "recette"),
                ).fetchone()
            if stored:
                return
        time.sleep(0.5)
    raise RuntimeError("Chrome n’a pas persisté le cookie de recette en 90 secondes.")


def browser_phase(chrome, profile, extension, phase, nonce, image, proof):
    command = [
        chrome,
        f"--user-data-dir={profile}",
        f"--load-extension={extension}",
        f"--disable-extensions-except={extension}",
        "--disable-background-networking",
        "--no-first-run",
        "about:blank",
    ]
    log = (
        (proof / "chrome.log").open("wb")
        if phase == "secret"
        else nullcontext(subprocess.DEVNULL)
    )
    with (
        log as diagnostic,
        subprocess.Popen(command, stdout=diagnostic, stderr=diagnostic) as browser,
    ):
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if browser.poll() is not None:
                    raise RuntimeError(
                        f"Chrome a quitté avec le code {browser.returncode}. Vérifier DISPLAY."
                    )
                sessions = subprocess.check_output(
                    ["browsentic", "sessions"], text=True, timeout=10
                )
                if any(line.startswith("●") for line in sessions.splitlines()):
                    result = worker(phase, nonce, image, proof)
                    if phase == "start":
                        wait_for_cookie_commit(profile)
                    return result
                time.sleep(1)
            raise RuntimeError("Aucun profil de recette appairé en 90 secondes.")
        finally:
            browser.terminate()
            try:
                browser.wait(timeout=15)
            except subprocess.TimeoutExpired:
                browser.kill()
                raise


def secret_phase(chrome, profile, extension, image, proof, home):
    canary = secrets.token_hex(32).encode()
    source = proof / "canary"
    with source.open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(canary)
    try:
        result = browser_phase(chrome, profile, extension, "secret", "", image, proof)
        for root in (proof, home / "bridge", profile):
            for path in root.rglob("*"):
                if path.is_file() and not path.is_symlink() and path != source:
                    data = path.read_bytes()
                    if canary in data or canary.decode().encode("utf-16-le") in data:
                        raise RuntimeError("Valeur factice trouvée dans " + path.name)
        if result:
            raise RuntimeError("Saisie protégée en échec, consulter worker-mcp.log")
        print(
            "Empreinte du champ vérifiée. Valeur absente du prompt, des checkpoints "
            "SQLite et des journaux du worker, du MCP et du Bridge."
        )
        return 0
    finally:
        source.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", required=True, type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--secret", action="store_true", help="Tester la saisie protégée"
    )
    parser.add_argument("--image", default="linkedin-browsentic-recette")
    modes.add_argument(
        "--pdf-panneau",
        action="store_true",
        help="Attendre la sélection de recette.pdf dans le panneau Browsentic",
    )
    modes.add_argument("--verified-documents", type=Path, metavar="EXTENSION_BUILD")
    parser.add_argument("--isolated", metavar="PARENT_NETNS", help=argparse.SUPPRESS)
    args = parser.parse_args()
    chrome = args.chrome.resolve(strict=True)
    if not args.isolated:
        command = [
            "unshare",
            "--user",
            "--map-current-user",
            "--net",
            "--keep-caps",
            sys.executable,
            str(Path(__file__).resolve()),
            "--isolated",
            os.readlink("/proc/self/ns/net"),
            "--chrome",
            str(chrome),
            "--image",
            args.image,
        ]
        if args.pdf_panneau:
            command.append("--pdf-panneau")
        if args.secret:
            command.append("--secret")
        if args.verified_documents:
            command += [
                "--verified-documents",
                str(args.verified_documents.resolve(strict=True)),
            ]
        return subprocess.run(command, check=False).returncode

    # Un argument interne seul ne doit jamais démarrer un Bridge sur le réseau du poste.
    if os.readlink("/proc/self/ns/net") == args.isolated:
        raise RuntimeError("Espace réseau isolé requis")
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    interfaces = {
        line.split(":")[0].strip()
        for line in Path("/proc/net/dev").read_text().splitlines()[2:]
    }
    if interfaces != {"lo"}:
        raise RuntimeError("La recette requiert uniquement le loopback")
    root_tmp = ROOT / "tmp"
    root_tmp.mkdir(exist_ok=True)
    state = Path(tempfile.mkdtemp(prefix="browsentic-", dir=root_tmp))
    proof = state / "preuve"
    proof.mkdir()
    print(f"Preuves locales dans {proof}", flush=True)
    with tempfile.TemporaryDirectory(dir=state) as scratch:
        home = Path(scratch)
        profile = home / ".config/chromium"
        profile.mkdir(parents=True)
        extension = home / "extension"
        # Le lanceur natif, le code d’appairage et le profil sont propres à cette exécution.
        xauth = os.environ.get("XAUTHORITY", str(Path.home() / ".Xauthority"))
        runtime = {
            key: os.environ[key]
            for key in ("PATH", "DISPLAY", "LANG")
            if key in os.environ
        }
        os.environ.clear()
        os.environ.update(
            runtime,
            HOME=scratch,
            BROWSENTIC_HOME=str(home / "bridge"),
            XDG_CONFIG_HOME=str(home / ".config"),
            XDG_CACHE_HOME=str(home / ".cache"),
            XAUTHORITY=xauth,
            DBUS_SESSION_BUS_ADDRESS="disabled:",
        )
        with portal() as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                subprocess.run(
                    [
                        "browsentic",
                        "setup",
                        "--no-self-update",
                        "--unpacked",
                        "--browser",
                        "chromium",
                        "--dir",
                        str(extension),
                        "--no-open",
                        "--no-pair",
                        "--no-wait",
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
                if args.verified_documents:
                    shutil.copytree(
                        args.verified_documents, extension, dirs_exist_ok=True
                    )
                    config = home / "bridge" / "config.json"
                    config.parent.mkdir(mode=0o700, exist_ok=True)
                    settings = json.loads(config.read_text()) if config.exists() else {}
                    settings.setdefault("guardrails", {}).setdefault(
                        "rules", {}
                    ).update({"file-upload": "allow", "file-download": "allow"})
                    config.write_text(json.dumps(settings))
                    config.chmod(0o600)
                    return browser_phase(
                        chrome,
                        profile,
                        extension,
                        "verified-documents",
                        server.nonce,
                        args.image,
                        proof,
                    )
                if args.pdf_panneau:
                    print(
                        f"PDF à sélectionner dans le panneau Browsentic : {HERE / 'recette.pdf'}",
                        flush=True,
                    )
                    return browser_phase(
                        chrome,
                        profile,
                        extension,
                        "pdf-panel",
                        server.nonce,
                        args.image,
                        proof,
                    )
                if args.secret:
                    return secret_phase(
                        chrome, profile, extension, args.image, proof, home
                    )
                start = browser_phase(
                    chrome, profile, extension, "start", server.nonce, args.image, proof
                )
                resume = browser_phase(
                    chrome,
                    profile,
                    extension,
                    "resume",
                    server.nonce,
                    args.image,
                    proof,
                )
                return start or resume
            finally:
                server.shutdown()
                subprocess.run(
                    ["browsentic", "stop"], stdout=subprocess.DEVNULL, check=False
                )


if __name__ == "__main__":
    sys.exit(main())
