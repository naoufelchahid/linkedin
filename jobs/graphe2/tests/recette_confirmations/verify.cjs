// Les deux espaces de recette sont servis exclusivement depuis la mémoire de Chrome.
const {chromium} = require(process.env.PLAYWRIGHT);
const {createInterface} = require('node:readline');
const {once} = require('node:events');

async function main() {
  const input = createInterface({input: process.stdin});
  const [line] = await once(input, 'line');
  input.close();
  const {space, token, digest} = JSON.parse(line);
  if (!['A', 'B'].includes(space) || !/^G15-[AB]-[0-9a-f]{12}$/.test(token)) throw Error();
  const browser = await chromium.launch({executablePath: process.env.CHROME});
  try {
    const page = await browser.newPage();
    const url = 'https://portail.invalid/' + space + '/confirmation';
    await page.route('**/*', route => route.request().url() === url
      ? route.fulfill({contentType: 'text/html', body:
        '<form><input id="code" type="password" required><button>Confirmer</button></form><output></output>'})
      : route.abort());
    await page.goto(url);
    await page.evaluate(expected => {
      document.querySelector('form').onsubmit = async event => {
        event.preventDefault();
        const bytes = new TextEncoder().encode(document.querySelector('#code').value);
        const hash = await crypto.subtle.digest('SHA-256', bytes);
        const hex = Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2,'0')).join('');
        document.querySelector('output').textContent = hex === expected ? 'actif' : 'en attente';
        document.querySelector('#code').value = '';
      };
    }, digest);
    await page.locator('#code').fill(token);
    await page.locator('button').click();
    await page.waitForFunction(() => document.querySelector('output').textContent === 'actif');
  } finally { await browser.close(); }
}
main().catch(() => { process.exitCode = 1; });
