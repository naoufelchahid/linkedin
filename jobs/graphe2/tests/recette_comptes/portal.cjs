// Le navigateur ne sert que les deux espaces synthétiques en mémoire.
const {chromium} = require(process.argv[2])
const {createHash} = require('node:crypto')
const {createInterface} = require('node:readline')
const allowed = ['https://portail.invalid/a', 'https://portail.invalid/b']
async function main() {
  const browser = await chromium.launch({executablePath:process.argv[3], headless:true})
  const accounts = new Map()
  const page = await browser.newPage()
  await page.route('**/*', async route => {
    if (!allowed.includes(route.request().url())) return route.abort()
    if (route.request().method() === 'POST') {
      const params = new URLSearchParams(route.request().postData())
      const digest = createHash('sha256').update(params.get('password')).digest('hex')
      const key = route.request().url()
      const saved = accounts.get(key)
      const login = params.get('email')
      const ok = saved ? saved.digest === digest && saved.login === login : ![...accounts.values()].some(row => row.digest === digest)
      if (!saved && ok) accounts.set(key, {login, digest})
      return route.fulfill({status:200,contentType:'text/html; charset=utf-8',body:ok ? (saved ? 'Retrouvé' : 'Créé') : 'Erreur'})
    }
    return route.fulfill({contentType:'text/html; charset=utf-8',body:'<form method="post"><input type="email" name="email" required><input type="password" name="password" required><button>Valider</button></form>'})
  })
  try {
    for await (const line of createInterface({input:process.stdin})) {
      const args = JSON.parse(line)
      let result = true
      if (args.cmd === 'open') await page.goto(allowed[args.space])
      else if (args.cmd === 'url') result = page.url()
      else if (args.cmd === 'fill') await page.locator(args.selector).fill(args.value)
      else if (args.cmd === 'submit') {
        await Promise.all([page.waitForNavigation(),page.locator('button').click()])
        result = await page.locator('body').innerText()
      } else throw new Error('action inconnue')
      console.log(JSON.stringify(result))
    }
  } finally { await browser.close() }
}
main().catch(() => {process.exitCode = 1})
