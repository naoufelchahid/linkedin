// Double MCP de recette. Chrome reçoit uniquement les deux pages synthétiques.
const { chromium } = require(process.argv[2]);
const { randomBytes } = require("node:crypto");
const readline = require("node:readline");
const { appendFileSync } = require("node:fs");

const site = "https://recette.invalid";
const slug = process.argv[3],
  proof = process.argv[4];
const title = slug === "atelier" ? "Analyste Atelier" : "Consultant Bureau";
const url = site + "/" + slug;
const id = () => "f" + randomBytes(6).toString("hex");
const [frameId, nameId, remoteId, cityId, buttonId] = Array.from(
  { length: 5 },
  id,
);
const atelier = slug === "atelier";
const name = `<label>${atelier ? "Nom du candidat" : "Identité complète"}<input required id="${nameId}"></label>`;
const choice = `<label>${atelier ? "Travail à distance" : "Souhaitez-vous télétravailler ?"}<select required id="${remoteId}"><option value="">Choisir</option><option>Oui</option><option>Non</option></select></label>`;
const city = `<label hidden>${atelier ? "Ville de rattachement" : "Dans quelle commune êtes-vous rattaché ?"}<input id="${cityId}"></label>`;
const frameHtml =
  "<form><h2>" +
  title +
  "</h2>" +
  (slug === "atelier" ? name + choice : choice + name) +
  city +
  '<button id="' +
  buttonId +
  '">Déposer le dossier</button></form>' +
  '<script>const city=document.querySelector("[hidden]"), select=document.querySelector("select");' +
  'select.onchange=()=>{city.hidden=select.value!=="Oui";city.firstElementChild.required=!city.hidden};' +
  `document.querySelector("form").onsubmit=e=>{e.preventDefault();
    if(document.getElementById("${nameId}").value==="Camille Exemple" && select.value==="Oui" &&
       city.firstElementChild.value==="Rabat")parent.postMessage("depot-local",location.origin);
    else document.body.append("Les réponses doivent correspondre aux faits du dossier.");
  };</script>`;

const tools = [
  [
    "page_openTab",
    { url: "string" },
    "Ouvrir la page de cette offre de recette.",
  ],
  [
    "page_getPageInfo",
    {},
    "Observer URL, cadres, champs, options et boutons visibles du cadre actif.",
  ],
  [
    "page_switchFrame",
    { selector: "string" },
    "Entrer dans le cadre observé avec son sélecteur.",
  ],
  [
    "page_fillInput",
    { selector: "string", value: "string" },
    "Renseigner le champ indiqué.",
  ],
  [
    "page_selectOption",
    { selector: "string", value: "string" },
    "Choisir une des options visibles.",
  ],
  ["page_clickElement", { selector: "string" }, "Cliquer le bouton indiqué."],
  ["page_extractText", {}, "Lire le texte visible du cadre actif."],
].map(([name, fields, description]) => ({
  name,
  description,
  inputSchema: {
    type: "object",
    properties: Object.fromEntries(
      Object.entries(fields).map(([k, type]) => [k, { type }]),
    ),
    required: Object.keys(fields),
  },
}));

async function main() {
  const chrome = await chromium.launch({
    executablePath: process.argv[5],
    headless: true,
  });
  try {
    const page = await chrome.newPage({ serviceWorkers: "block" });
    let frame = page.mainFrame(),
      clicks = 0;
    await page.route("**/*", async (route) => {
      const requested = route.request().url();
      if (![url, url + "/frame"].includes(requested)) return route.abort();
      const body = requested.endsWith("/frame")
        ? frameHtml
        : "<h1>" +
          title +
          '</h1><iframe id="' +
          frameId +
          '" src="' +
          url +
          '/frame"></iframe>';
      await route.fulfill({ contentType: "text/html;charset=utf-8", body });
    });
    await page.exposeFunction("recetteDeposee", async () => {
      clicks++;
      appendFileSync(proof, JSON.stringify({ slug, clicks }) + "\n");
    });
    await page.addInitScript(
      ({ slug, title }) => {
        if (window !== top) return;
        window.onmessage = async (e) => {
          if (
            e.origin !== location.origin ||
            e.source !== document.querySelector("iframe")?.contentWindow ||
            e.data !== "depot-local"
          )
            return;
          await window.recetteDeposee();
          document.body.textContent =
            slug === "atelier"
              ? "Candidature reçue pour " + title + " — reçu A-237"
              : "Service indisponible après validation";
        };
      },
      { slug, title },
    );
    async function call(name, args) {
      if (name === "page_openTab") {
        if (args.url !== url) throw Error("Offre hors recette");
        await page.goto(url);
        frame = page.mainFrame();
        return { tabId: 1, url };
      }
      if (frame.isDetached()) frame = page.mainFrame();
      if (name === "page_getPageInfo")
        return frame.evaluate(() => ({
          tabId: 1,
          url: location.href,
          frames: [...document.querySelectorAll("iframe")].map((e) => ({
            selector: "#" + e.id,
          })),
          interactive: [...document.querySelectorAll("input,select,button")]
            .filter((e) => e.getClientRects().length)
            .map((e) => ({
              selector: "#" + e.id,
              label: e.labels?.[0]?.firstChild.textContent || e.textContent,
              value: e.value,
              type: e.type,
              required: e.required,
              validation: e.validationMessage,
              options: e.options
                ? [...e.options].map((o) => o.value)
                : undefined,
            })),
        }));
      if (name === "page_extractText")
        return { text: await frame.locator("body").innerText() };
      if (name === "page_switchFrame") {
        const element = await page
          .locator(args.selector)
          .elementHandle({ timeout: 2000 });
        frame = await element.contentFrame();
        return { active: true };
      }
      const field = frame.locator(args.selector);
      if (name === "page_fillInput")
        await field.fill(args.value, { timeout: 2000 });
      else if (name === "page_selectOption")
        await field.selectOption(args.value, { timeout: 2000 });
      else if (name === "page_clickElement")
        await field.click({ timeout: 2000 });
      else throw Error("Action indisponible");
      return { ok: true };
    }
    const input = readline.createInterface({ input: process.stdin });
    for await (const line of input) {
      const msg = JSON.parse(line);
      if (msg.id === undefined) continue;
      let result;
      if (msg.method === "initialize")
        result = {
          protocolVersion: msg.params.protocolVersion,
          capabilities: { tools: {} },
          serverInfo: { name: "fixture", version: "1" },
        };
      else if (msg.method === "tools/list") result = { tools };
      else if (msg.method === "tools/call") {
        try {
          result = {
            content: [
              {
                type: "text",
                text: JSON.stringify(
                  await call(msg.params.name, msg.params.arguments || {}),
                ),
              },
            ],
          };
        } catch {
          result = {
            isError: true,
            content: [
              { type: "text", text: "Action indisponible dans le cadre actif" },
            ],
          };
        }
      } else result = {};
      console.log(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result }));
    }
  } finally {
    await chrome.close();
  }
}
main().catch(() => (process.exitCode = 1));
