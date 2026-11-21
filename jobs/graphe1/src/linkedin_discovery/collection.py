"""Démarrage et rattachement des runs de collecte par profil."""

from .errors import ConnectorError


def _profile_run(store, cycle_id, profile):
    return store.db.execute(
        "SELECT * FROM runs WHERE cycle_id=? AND profile=?", (cycle_id, profile)
    ).fetchone()


def _record_run(store, cycle_id, profile, run_id, run):
    store.execute(
        "UPDATE runs SET run_id=?,dataset_id=?,status=?,error='' WHERE cycle_id=? AND profile=?",
        (run_id, run.get("defaultDatasetId"), run["status"], cycle_id, profile),
    )


def attach_profile_run(store, apify, cycle_id, profile, run_id, settings):
    run = apify.run(run_id)
    actor_id = apify.actor_id(settings["actor"])
    input_data = apify.run_input(run["defaultKeyValueStoreId"])
    if (
        profile not in settings["profiles"]
        or run["actId"] != actor_id
        or input_data.get("keywords") != profile
        or input_data.get("location") != settings.get("location", "Morocco")
        or input_data.get("datePosted") != settings.get("period", "r604800")
        or input_data.get("limit") != settings["limit"]
    ):
        raise ValueError("run_input_mismatch")
    existing = _profile_run(store, cycle_id, profile)
    if existing is None or existing["run_id"]:
        raise ValueError("run_attachment_not_needed")
    _record_run(store, cycle_id, profile, run_id, run)


def start_profile_run(store, apify, cycle_id, profile, settings):
    row = _profile_run(store, cycle_id, profile)
    if row:
        if row["status"] == "STARTING":
            store.execute(
                "UPDATE runs SET status='START_UNCERTAIN',error='start_interrupted_verify_run' WHERE cycle_id=? AND profile=?",
                (cycle_id, profile),
            )
        return
    store.execute(
        "INSERT INTO runs(cycle_id,profile,status) VALUES(?,?,?)",
        (cycle_id, profile, "STARTING"),
    )
    try:
        filters = {k: settings[k] for k in ("location", "period") if k in settings}
        run = apify.start(profile, settings["limit"], **filters)
        _record_run(store, cycle_id, profile, run["id"], run)
    except (ConnectorError, KeyError, TypeError):
        # Ne pas relancer un POST dont la réception est incertaine.
        store.execute(
            "UPDATE runs SET status='START_UNCERTAIN',error='apify_start_failed_verify_run' WHERE cycle_id=? AND profile=?",
            (cycle_id, profile),
        )
