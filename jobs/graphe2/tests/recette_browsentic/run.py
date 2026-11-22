"""Recette Linux du worker Docker vers le Bridge et le navigateur sur l’hôte."""

import argparse
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from portal import portal

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def worker(phase, nonce, image, proof):
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
    with subprocess.Popen(
        ["browsentic", "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
    ) as mcp:
        try:
            return subprocess.run(
                command, stdin=mcp.stdout, stdout=mcp.stdin, timeout=150, check=False
            ).returncode
        except subprocess.TimeoutExpired:
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
    with subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ) as browser:
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", required=True, type=Path)
    parser.add_argument("--image", default="linkedin-browsentic-recette")
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
