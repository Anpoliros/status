/** Browser checks for origin telemetry disclosure, ranges and mobile overflow. */
const { chromium } = require(process.env.STATUS_PLAYWRIGHT_PATH || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage({viewport:{width:1280,height:900}});
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  const config = require('node:child_process').execFileSync('.venv/bin/python', ['-c',
    "from backend.status_monitor.config import load_config; print(load_config().status_json)"]).toString().trim();
  const payload = JSON.parse(require('node:fs').readFileSync(config));
  await page.route('**/api/session', route => route.fulfill({json:{full_access:true,refresh:{presets:[10,20,60],minimum_seconds:10}}}));
  await page.route('**/status', route => route.fulfill({json:payload}));
  await page.route('**/api/control', route => route.fulfill({json:{}}));
  await page.goto('http://127.0.0.1:18080');
  await page.getByRole('button',{name:'Services',exact:true}).click();
  const telemetry = page.locator('.serviceTelemetry').first();
  await telemetry.locator('summary').click();
  await telemetry.getByRole('button',{name:'24 hours',exact:true}).click();
  await telemetry.getByRole('button',{name:'60 days',exact:true}).click();
  assert.equal(await page.locator('.serviceTelemetry').count(),3);
  assert.equal(await telemetry.locator('svg').count(),1);
  await page.screenshot({path:'/tmp/status-telemetry-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({path:'/tmp/status-telemetry-mobile.png',fullPage:true});
  assert.deepEqual(errors,[]);
  await browser.close();
  console.log('Telemetry desktop/mobile checks passed');
})().catch(error => {console.error(error);process.exit(1);});
