"""CLI explicite du pilote ; aucun cron ni service actif n'est modifié."""

import argparse
import json
import os
import shutil
import signal
import sqlite3
import sys
from pathlib import Path

import psycopg

from .config import Config
from .connectors import ConnectorError
from .workflow import DiscoveryService


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        description="Graphe 1 : découverte et qualification des offres"
    )
    parser.add_argument("--home", type=Path, help="Répertoire de configuration (.env, var)")
    parser.add_argument("--env-file", type=Path, help="Fichier privé de configuration explicite")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Diagnostic local, sans appel fournisseur")
    discover = commands.add_parser("discover", help="Nouvelle collecte Apify et qualification")
    discover.add_argument(
        "--daily", action="store_true", help="Reprendre le cycle du jour au lieu de le dupliquer"
    )
    discover.add_argument(
        "--fail-on-errors",
        action="store_true",
        help="Code de sortie 3 si le bilan contient des erreurs",
    )
    status = commands.add_parser("status", help="État du dernier cycle ou d’un cycle précis")
    status.add_argument("--cycle")
    backup = commands.add_parser("backup", help="Sauvegarder et vérifier l’état privé")
    backup.add_argument("--destination", type=Path)
    verify = commands.add_parser(
        "verify-backup", help="Vérifier une sauvegarde sans remplacer les données actives"
    )
    verify.add_argument("archive", type=Path)
    resume = commands.add_parser(
        "resume", help="Relire les runs du cycle et poursuivre sans les relancer"
    )
    resume.add_argument("cycle")
    resume.add_argument("--fail-on-errors", action="store_true")
    report = commands.add_parser("report", help="Créer une nouvelle version figée du rapport")
    report.add_argument("cycle")
    review = commands.add_parser("review", help="Enregistrer la correction reçue du candidat")
    review.add_argument("--report", required=True)
    review.add_argument("--number", type=int, required=True)
    review.add_argument("--verdict", choices=["retenir", "écarter"], required=True)
    review.add_argument("--note", default="")
    validation = commands.add_parser(
        "validate-report", help="Enregistrer l’accord global sur ce rapport"
    )
    validation.add_argument("--report", required=True)
    replay = commands.add_parser(
        "replay", help="Rejouer exactement les annonces du rapport avec le CV sauvegardé"
    )
    replay.add_argument("--report", required=True)
    replay.add_argument("--prompt-file", type=Path)
    replay.add_argument("--fail-on-errors", action="store_true")
    compare = commands.add_parser(
        "compare", help="Comparer le rejeu aux verdicts humains du rapport"
    )
    compare.add_argument("--report", required=True)
    compare.add_argument("--cycle", required=True)
    attach = commands.add_parser(
        "attach-run", help="Rapprocher un run après un lancement incertain"
    )
    attach.add_argument("--cycle", required=True)
    attach.add_argument("--profile", required=True)
    attach.add_argument("--run", required=True)
    args = parser.parse_args(argv)
    config = Config.load(root=args.home, env_file=args.env_file)
    if args.command == "doctor":
        result = dict(
            apify_configured=bool(config.token),
            cv_exists=bool(config.cv and config.cv.is_file()),
            cv_path=str(config.cv) if config.cv else None,
            codex_available=bool(shutil.which("codex")),
            pdftotext_available=bool(shutil.which("pdftotext")),
            langsmith_configured=bool(config.langsmith_key),
            data_path=str(config.data),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return (
            0
            if all(
                result[k]
                for k in ("apify_configured", "cv_exists", "codex_available", "pdftotext_available")
            )
            else 2
        )
    pilot = DiscoveryService(config)
    try:
        if args.command == "discover":
            if not config.token:
                raise ConnectorError("apify_token_missing")
            with pilot.store.locked():
                result = pilot.run(pilot.daily_cycle() if args.daily else pilot.create())
        elif args.command == "resume":
            result = pilot.run(args.cycle)
        elif args.command == "report":
            with pilot.store.locked():
                result = pilot.report({"cycle_id": args.cycle})
        elif args.command == "review":
            with pilot.store.locked():
                pilot.store.review(args.report, args.number, args.verdict, args.note)
            result = dict(
                status="recorded", report_id=args.report, number=args.number, verdict=args.verdict
            )
        elif args.command == "validate-report":
            with pilot.store.locked():
                pilot.store.validate_report(args.report)
            result = dict(status="validated", report_id=args.report)
        elif args.command == "replay":
            prompt = args.prompt_file.read_text() if args.prompt_file else None
            with pilot.store.locked():
                result = pilot.run(pilot.replay(args.report, prompt))
        elif args.command == "compare":
            result = pilot.compare(args.report, args.cycle)
        elif args.command == "attach-run":
            with pilot.store.locked():
                result = pilot.attach_run(args.cycle, args.profile, args.run)
        elif args.command == "status":
            result = pilot.status(args.cycle)
        elif args.command == "backup":
            from .maintenance import backup_state

            with pilot.store.locked():
                destination = args.destination or config.root / "backups"
                result = backup_state(pilot.store, destination)
        elif args.command == "verify-backup":
            from .maintenance import verify_backup

            result = verify_backup(args.archive)
        incomplete = False
        if args.command in {"discover", "resume", "replay"}:
            counts = pilot.status(result["cycle_id"])["qualifications"]
            result["qualification_counts"] = counts
            incomplete = result["status"] == "partial" or any(
                counts.get(k, 0) for k in ("error", "data_problem", "pending")
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 3 if incomplete and getattr(args, "fail_on_errors", False) else 0
    finally:
        pilot.store.close()


def entrypoint(argv=None):
    def interrupted(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        code = main(argv)
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted", "code": "resume_same_cycle"}), file=sys.stderr)
        code = 130
    except (ConnectorError, ValueError, OSError, RuntimeError, sqlite3.Error, psycopg.Error) as exc:
        safe = {
            "cycle_not_found",
            "report_not_found",
            "report_item_not_found",
            "invalid_human_verdict",
            "discovery_already_running",
            "database_schema_version_unsupported",
            "backup_integrity_failed",
            "backup_destination_inside_state",
            "run_input_mismatch",
            "run_attachment_not_needed",
            "saved_cv_integrity_failed",
        }
        message = str(exc)
        code_name = (
            message
            if isinstance(exc, ConnectorError) or message in safe
            else "discovery_operation_failed"
        )
        print(json.dumps({"status": "error", "code": code_name}), file=sys.stderr)
        code = 1
    raise SystemExit(code)
