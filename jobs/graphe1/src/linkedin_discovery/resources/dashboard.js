const view = document.querySelector("#view");
const message = document.querySelector("#message");
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const safeURL = (value) => {
  try {
    const u = new URL(value);
    return ["http:", "https:"].includes(u.protocol) ? u.href : "";
  } catch {
    return "";
  }
};
const date = (value) =>
  value && Number.isFinite(Date.parse(value))
    ? new Date(value).toLocaleDateString("fr-FR", {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    : "Non précisée";
const fmt = (n) => n.toLocaleString("fr-FR");
let data,
  generation = 0,
  timer;
const node = (id) => document.getElementById(id);
async function api(command, payload) {
  const res = await fetch("/dashboard/actions/" + command, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw Error((await res.json()).error || "Action indisponible.");
  return res.json();
}
function notify(text) {
  message.textContent = text;
}
function table(head, rows, empty) {
  return (
    '<div class="scroll"><table><thead><tr>' +
    head.map((h) => "<th>" + h + "</th>").join("") +
    "</tr></thead><tbody>" +
    (rows.join("") ||
      '<tr><td colspan="' + head.length + '">' + esc(empty) + "</td></tr>") +
    "</tbody></table></div>"
  );
}
function offers(params) {
  const cycle = params.get("cycle") || "";
  const page = generation;
  const checked = new Set();
  let dossiers = {};
  let eligible = 0;
  let launching = false;
  view.innerHTML =
    '<h1>Offres retenues</h1><div class="tools"><label>Rechercher<input id="query" type="search" placeholder="Poste ou descriptif"></label><label>Entreprise<select id="company"></select></label><label>Lieu<select id="location"></select></label><label>Trier par<select id="sort"><option value="since">Découverte</option><option value="posted_at">Publication</option></select></label></div>' +
    (cycle
      ? '<p>Offres du cycle · <a href="#offres">Voir toutes les offres</a></p>' +
        '<div class="tools"><span id="applicationsStatus"></span>' +
        '<label>Mode<select id="applicationsMode"><option value="recipe">Recette</option>' +
        '<option value="production">Production</option></select></label>' +
        '<span id="recipeSelection"></span>' +
        '<button id="applicationsLaunch" disabled>Lancer les candidatures</button></div>'
      : "") +
    '<p id="count"></p><div id="rows"></div>';
  if (cycle) {
    const status = node("applicationsStatus");
    const button = node("applicationsLaunch");
    async function refreshApplications() {
      try {
        const result = await api("application-status", { cycle });
        if (page !== generation) return;
        dossiers = result.dossiers || {};
        eligible = result.prioritaires + result.incertaines;
        status.textContent = `${result.prioritaires} prioritaires · ${result.incertaines} incertaines`;
        if (result.confirmed_today != null)
          status.textContent += ` · ${result.confirmed_today} dépôts confirmés aujourd’hui`;
        render();
      } catch (e) {
        status.textContent = e.message;
      }
    }
    refreshApplications();
    timer = setInterval(refreshApplications, 8000);
    button.onclick = async () => {
      launching = true;
      button.disabled = true;
      try {
        const mode = node("applicationsMode").value;
        const offers = mode === "recipe" ? [...checked] : [];
        const result = await api("applications", { cycle, mode, offers });
        notify(`Lot de candidatures ${result.lot} lancé.`);
      } catch (e) {
        notify(e.message);
      } finally {
        launching = false;
        await refreshApplications();
      }
    };
  }
  for (const [id, label] of [
    ["company", "Toutes"],
    ["location", "Tous"],
  ]) {
    node(id).add(new Option(label, ""));
    [...new Set(data.offers.map((o) => o[id]).filter(Boolean))]
      .sort()
      .forEach((v) => node(id).add(new Option(v, v)));
  }
  function render() {
    const recipe = cycle && node("applicationsMode").value === "recipe";
    if (cycle) {
      node("recipeSelection").textContent = recipe
        ? checked.size ? `${checked.size} sélectionnée(s)` : "Coche les offres à essayer"
        : "";
      node("applicationsLaunch").disabled = launching || !eligible || (recipe && !checked.size);
    }
    const q = node("query").value.trim().toLocaleLowerCase();
    const rows = data.offers
      .filter(
        (o) =>
          (o.title + " " + o.description).toLocaleLowerCase().includes(q) &&
          ["company", "location"].every(
            (k) => !node(k).value || o[k] === node(k).value,
          ),
      )
      .sort(
        (a, b) =>
          (Date.parse(b[node("sort").value]) || 0) -
          (Date.parse(a[node("sort").value]) || 0),
      );
    node("count").textContent =
      fmt(rows.length) +
      (rows.length > 1 ? " offres retenues" : " offre retenue");
    node("rows").innerHTML = table(
      [...(recipe ? ["Recette"] : []), "Poste et missions", "Entreprise", "Lieu", "Publication", "Candidature"],
      rows.map(
        (o) =>
          "<tr>" +
          (recipe
            ? '<td><input type="checkbox" data-recipe-offer="' + esc(o.key) +
              '" aria-label="Essayer ' + esc(o.title) + '"' + (checked.has(o.key) ? " checked" : "") + "></td>"
            : "") +
          '<td><a href="#fiche?' +
          new URLSearchParams({ offer: o.key, cycle }) +
          '"><b>' +
          esc(o.title) +
          "</b></a><small>" +
          esc(o.description.slice(0, 155)) +
          "</small></td><td>" +
          esc(o.company) +
          "</td><td>" +
          esc(o.location) +
          "</td><td>" +
          esc(date(o.posted_at)) +
          '</td><td><span class="badge">' +
          esc({
            submitted: "Soumise",
            submission_uncertain: "Envoi à vérifier",
            waiting: "Intervention requise",
            deferred: "Reportée",
            recipe_ready: "Recette prête",
            version_conflict: "Destination à vérifier",
            blocked: "Bloquée",
            ready: "Prête au dépôt",
            preparing: "En préparation",
          }[dossiers[o.key]] || "Dans le pipe") +
          "</span></td></tr>",
      ),
      "Aucune offre retenue pour cette sélection.",
    );
  }
  view.oninput = (event) => {
    const key = event.target.dataset.recipeOffer;
    if (key) {
      if (event.target.checked) checked.add(key);
      else checked.delete(key);
      node("recipeSelection").textContent = checked.size
        ? `${checked.size} sélectionnée(s)`
        : "Coche les offres à essayer";
      node("applicationsLaunch").disabled = launching || !eligible || !checked.size;
      return;
    }
    render();
  };
  render();
}
const fieldNames = {
  title: "Intitulé du poste",
  location: "Lieu",
  companyName: "Entreprise",
  companyUrl: "Page de l’entreprise",
  contractType: "Contrat",
  experienceLevel: "Expérience",
  applicationsCount: "Candidatures sur l’annonce",
  applyType: "Mode de candidature",
  applyUrl: "Page de candidature",
  salary: "Rémunération",
  postedDate: "Date de publication",
  postedTimeAgo: "Ancienneté lors de la collecte",
  sector: "Secteur déclaré",
  workType: "Activité déclarée",
  recruiterName: "Contact recrutement",
  recruiterUrl: "Profil du recruteur",
  id: "Référence de l’annonce",
  description: "Descriptif",
  descriptionHtml: "Descriptif mis en forme",
  url: "Annonce d’origine",
};
const terms = new Map(
  Object.entries({
    EXTERNAL: "Sur le site de recrutement",
    EASY_APPLY: "Candidature simplifiée",
    "Full-time": "Temps plein",
    "Part-time": "Temps partiel",
    Volunteer: "Bénévolat",
    Internship: "Stage",
    Contract: "Sous contrat",
    Other: "Autre",
    "Not Applicable": "Non précisé",
    "Mid-Senior level": "Confirmé à senior",
    Associate: "Intermédiaire",
    "Entry level": "Débutant",
    Executive: "Direction",
    Director: "Direction",
    Remote: "Télétravail",
    Hybrid: "Hybride",
    "On-site": "Sur site",
    "Be among the first 25 applicants": "Parmi les 25 premiers candidats",
    "Over 200 applicants": "Plus de 200 candidatures",
  }),
);
function fieldLabel(key) {
  const words = key.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ");
  return fieldNames[key] || words.charAt(0).toUpperCase() + words.slice(1);
}
function externalLink(value, label, style = "") {
  const href = safeURL(value);
  return href
    ? `<a class="${style}" href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`
    : "";
}
// Keep only typographic structure. Source markup never enters the live document.
function formattedDescription(html) {
  const template = document.createElement("template");
  template.innerHTML = html;
  const tags = new Set([
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "li",
    "ul",
    "ol",
    "h3",
    "h4",
    "div",
  ]);
  function format(n) {
    if (n.nodeType === Node.TEXT_NODE) return esc(n.textContent);
    if (n.nodeType !== Node.ELEMENT_NODE) return "";
    const tag = n.localName;
    if (["script", "style", "noscript", "template"].includes(tag)) return "";
    const children = Array.from(n.childNodes, format).join("");
    if (tag === "br") return "<br>";
    return tags.has(tag) ? `<${tag}>${children}</${tag}>` : children;
  }
  return Array.from(template.content.childNodes, format).join("");
}
function displayValue(key, value) {
  if (value == null || value === "") return "Non renseigné";
  if (Array.isArray(value))
    return (
      "<ul>" +
      value.map((v) => "<li>" + displayValue(key, v) + "</li>").join("") +
      "</ul>"
    );
  if (typeof value === "object") return facts(Object.entries(value));
  if (typeof value === "boolean") return value ? "Oui" : "Non";
  if (key === "descriptionHtml") return formattedDescription(value);
  if (key === "postedDate") return esc(date(value));
  if (safeURL(value))
    return externalLink(value, fieldNames[key] || "Ouvrir le lien");
  const text = String(value);
  const ago = text.match(/^(\d+) (minute|hour|day|week|month|year)s? ago$/i);
  if (ago) {
    const unit = {
      minute: "minute",
      hour: "heure",
      day: "jour",
      week: "semaine",
      month: "mois",
      year: "an",
    }[ago[2].toLowerCase()];
    return (
      "Il y a " +
      ago[1] +
      " " +
      unit +
      (+ago[1] > 1 && unit !== "mois" ? "s" : "")
    );
  }
  return esc(
    terms.get(text) || text.replace(/^(\d+) applicants?$/, "$1 candidature(s)"),
  );
}
function facts(entries) {
  return (
    '<dl class="facts">' +
    entries
      .map(
        ([key, value]) =>
          `<div><dt>${esc(fieldLabel(key))}</dt><dd>${displayValue(key, value)}</dd></div>`,
      )
      .join("") +
    "</dl>"
  );
}
function detail(params) {
  const back =
    "#offres?" + new URLSearchParams({ cycle: params.get("cycle") || "" });
  const returnLink = `<a class="return" href="${back}">← Offres retenues</a>`;
  if (!data.detail) {
    view.innerHTML = returnLink + "<h1>Offre indisponible</h1>";
    return;
  }
  const { offer: o, result: r, human, observations } = data.detail;
  const clean = (s) =>
    String(s ?? "")
      .replace(/\s+/g, " ")
      .trim();
  const observation = observations.find(
    (x) =>
      clean(x.raw.description) === clean(o.description) &&
      clean(x.raw.title) === clean(o.title),
  );
  const source = observation?.raw || {};
  const description = source.descriptionHtml
    ? formattedDescription(source.descriptionHtml)
    : esc(o.description);
  const conditions = Object.entries(source).filter(
    ([key, v]) =>
      ["contractType", "experienceLevel", "salary", "applyType"].includes(
        key,
      ) && v,
  );
  const archives = observations
    .map((x) => {
      const fields = Object.entries(x.raw).filter(
        ([k]) => !["description", "descriptionHtml"].includes(k),
      );
      const prose = x.raw.descriptionHtml
        ? formattedDescription(x.raw.descriptionHtml)
        : esc(x.raw.description);
      return `<details class="observation"><summary>${esc(x.profile)} <span>${esc(date(x.observed_at))}</span></summary>${facts(fields)}${prose ? `<details><summary>Lire le descriptif collecté</summary><div class="prose">${prose}</div></details>` : ""}</details>`;
    })
    .join("");
  view.innerHTML = `${returnLink}<div class="job-head"><div><h1>${esc(o.title)}</h1><p class="byline"><b>${esc(o.company)}</b> · ${esc(o.location || "Lieu non précisé")}</p></div>${externalLink(o.url, "Ouvrir l’annonce", "source-link")}</div>
    <div class="job-layout"><section class="job-copy"><h2>Présentation du poste</h2><div class="prose">${description || "Descriptif indisponible."}</div></section>
    <aside><section class="decision"><h2>Pourquoi cette offre est retenue</h2><p>${esc(r.motif || "Motif non renseigné.")}</p>
    ${r.mission_citee ? `<blockquote>${esc(r.mission_citee)}</blockquote>` : ""}<small>Verdict Codex · ${esc(r.verdict || "Indisponible")}${r.incertitude ? " · Missions incertaines" : ""}</small>
    ${human ? `<p>Décision du candidat · ${esc(human)}</p>` : ""}</section>
    <section class="job-facts"><h2>Repères</h2>${facts([["postedDate", o.posted_at], ...conditions])}
    <h3>Candidature</h3><p>Le suivi sera disponible avec le graphe 2.</p></section></aside></div>
    <section class="sources"><h2>Historique des collectes Apify</h2>${archives || "<p>Aucune collecte disponible.</p>"}</section>`;
}
function metrics() {
  const monday = new Date();
  monday.setHours(0, 0, 0, 0);
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
  const weeks = Array.from({ length: 8 }, (_, i) => {
    const start = new Date(monday);
    start.setDate(start.getDate() - (7 - i) * 7);
    const end = new Date(start);
    end.setDate(end.getDate() + 7);
    return {
      label: start.toLocaleDateString("fr-FR", {
        day: "2-digit",
        month: "2-digit",
      }),
      n: data.offers.filter(
        (o) => new Date(o.since) >= start && new Date(o.since) < end,
      ).length,
    };
  });
  const max = Math.max(1, ...weeks.map((w) => w.n));
  view.innerHTML =
    '<h1>Vue d’ensemble</h1><div class="cards"><div class="card"><a href="#offres">Offres retenues</a><strong>' +
    fmt(data.offers.length) +
    "</strong></div>" +
    [
      ["Dans le pipe", "pipe"],
      ["Soumissions en cours", "active"],
      ["Candidatures envoyées", "submitted"],
      ["Erreurs de soumission", "errors"],
    ]
      .map(([label, key]) => {
        const count = data.applications?.[key];
        const value = Number.isInteger(count)
          ? "<strong>" + fmt(count) + "</strong>"
          : '<strong aria-label="Indisponible">—</strong>';
        return '<div class="card">' + label + value + "</div>";
      })
      .join("") +
    '</div><h2>Nouvelles offres retenues par semaine</h2><div class="paper chart">' +
    weeks
      .map(
        (w) =>
          '<div class="bar">' +
          w.n +
          '<i style="height:' +
          Math.round((80 * w.n) / max) +
          'px"></i>' +
          w.label +
          "</div>",
      )
      .join("") +
    "</div>";
}
function launch() {
  view.innerHTML =
    '<h1>Lancer une découverte</h1><form id="launchForm" class="paper"><label>Recherche favorite<select id="favorite"><option value="">Paramètres initiaux</option></select></label><p><label>Mots-clés · une recherche par ligne<textarea id="profiles" rows="3" required></textarea></label></p><div class="formgrid"><label>Lieu commun<input required id="place"></label><label>Publication<select id="period"><option value="r86400">24 dernières heures</option><option value="r604800">7 derniers jours</option><option value="r2592000">30 derniers jours</option></select></label><label>Résultats par recherche<input type="number" min="1" max="100" required id="limit"></label></div><p id="maximum"></p><button type="submit" class="primary">Lancer la découverte</button><details><summary>Enregistrer un favori</summary><div class="actions"><label>Nom du favori<input id="favName"></label><button type="button" id="save">Enregistrer le favori</button></div></details></form><h2>Suivi des cycles</h2><div id="progress" role="status"></div><div id="cycles"></div>';
  const search = () => ({
    profiles: node("profiles")
      .value.split("\n")
      .map((v) => v.trim())
      .filter(Boolean),
    location: node("place").value.trim(),
    period: node("period").value,
    limit: node("limit").valueAsNumber,
  });
  function maximum() {
    const s = search();
    node("maximum").textContent =
      "Maximum avant dédoublonnage · " +
      fmt(s.profiles.length * (s.limit || 0)) +
      " résultats";
  }
  function fill(s) {
    node("profiles").value = s.profiles.join("\n");
    node("place").value = s.location;
    node("period").value = s.period;
    node("limit").value = s.limit;
    maximum();
  }
  function options() {
    node("favorite").length = 1;
    Object.keys(data.favorites)
      .sort()
      .forEach((v) => node("favorite").add(new Option(v, v)));
  }
  options();
  fill(data.defaults);
  node("favorite").onchange = (e) => {
    const name = e.target.value;
    node("favName").value = name;
    fill(name ? data.favorites[name] : data.defaults);
  };
  node("launchForm").oninput = maximum;
  node("save").onclick = async () => {
    try {
      if (!node("launchForm").reportValidity()) return;
      const name = node("favName").value.trim();
      if (!name) {
        notify("Saisis un nom de favori.");
        return;
      }
      const s = search();
      await api("favorite", { name, search: s });
      data.favorites[name] = s;
      options();
      node("favorite").value = name;
      notify("Favori enregistré.");
    } catch (e) {
      notify(e.message);
    }
  };
  function history(rows) {
    node("cycles").innerHTML = table(
      ["Création", "Recherches", "État", "Actions"],
      rows.map((c) => {
        const s = JSON.parse(c.settings);
        const issues = c.errors || c.qualification_errors;
        const status = issues
          ? "Erreurs à examiner"
          : c.status === "partial"
            ? "Collecte partielle"
            : c.reports
              ? "Rapport disponible"
              : c.status === "collected"
                ? "Qualification"
                : "Collecte";
        return (
          "<tr><td>" +
          esc(new Date(c.created_at).toLocaleString("fr-FR")) +
          "</td><td>" +
          esc(s.profiles.join(", ")) +
          "<small>" +
          esc(s.location || "Morocco") +
          " · " +
          esc(s.limit) +
          " par recherche</small></td><td>" +
          status +
          "<small>" +
          c.qualified +
          ' qualification(s)</small></td><td><a href="#offres?cycle=' +
          encodeURIComponent(c.id) +
          '">Voir les offres</a>' +
          (!c.reports || issues || c.status === "partial"
            ? ' <button data-resume="' + esc(c.id) + '">Reprendre</button>'
            : "") +
          "</td></tr>"
        );
      }),
      "Aucun cycle lancé.",
    );
  }
  const stamp = generation;
  async function refresh() {
    const tracked = JSON.parse(localStorage.getItem("discovery.run") || "null");
    if (tracked) {
      try {
        const r = await api("progress", tracked);
        if (stamp !== generation) return;
        node("progress").textContent =
          "Dernier lancement · " +
          ({
            pending: "En attente",
            running: "En cours",
            success: "Terminé",
            error: "Échec",
            interrupted: "Interrompu",
            timeout: "Délai dépassé",
          }[r.status] || r.status);
      } catch {
        if (stamp === generation)
          node("progress").textContent = "Suivi du lancement indisponible.";
      }
    }
    const r = await fetch("/dashboard/data?cycles=1");
    if (!r.ok) throw Error("Lecture des cycles impossible.");
    const updated = await r.json();
    if (stamp === generation) history(updated.cycles);
  }
  async function run(button, command, payload) {
    button.disabled = true;
    try {
      const tracking = await api(command, payload);
      localStorage.setItem("discovery.run", JSON.stringify(tracking));
      notify("Lancement transmis à LangGraph.");
      await refresh();
    } catch (e) {
      notify(e.message);
    } finally {
      button.disabled = false;
    }
  }
  node("launchForm").onsubmit = (e) => {
    e.preventDefault();
    run(e.submitter, "launch", {
      cycle: crypto.randomUUID(),
      search: search(),
    });
  };
  node("cycles").onclick = (e) => {
    if (e.target.dataset.resume)
      run(e.target, "resume", { cycle: e.target.dataset.resume });
  };
  history(data.cycles);
  refresh().catch((e) => notify(e.message));
  timer = setInterval(() => refresh().catch((e) => notify(e.message)), 4500);
}
async function route() {
  const stamp = ++generation;
  clearInterval(timer);
  view.oninput = null;
  notify("");
  const [page = "offres", query = ""] = location.hash.slice(1).split("?");
  const params = new URLSearchParams(query);
  document
    .querySelectorAll("nav a")
    .forEach((a) =>
      a.toggleAttribute(
        "aria-current",
        a.hash === "#" + (page === "fiche" ? "offres" : page || "offres"),
      ),
    );
  try {
    if (page === "metrics") params.set("metrics", "1");
    const r = await fetch("/dashboard/data?" + params);
    if (!r.ok) throw Error();
    const loaded = await r.json();
    if (stamp !== generation) return;
    data = loaded;
    if (page === "metrics") metrics();
    else if (page === "fiche") detail(params);
    else if (page === "lancer") launch();
    else offers(params);
  } catch {
    if (stamp === generation)
      notify("Impossible de charger les données du tableau de bord.");
  }
}
window.addEventListener("hashchange", route);
route();
