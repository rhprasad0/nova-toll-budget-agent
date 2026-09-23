// Run: node v2/eval/evidence/gpt-6-luna/review-packet/check.mjs
import {chromium} from 'playwright';
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
/** @type {string[]} */
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto(new URL('./index.html', import.meta.url).href);
if(await page.locator('article.case').count()!==20)throw Error('case cap');
await page.locator('#next').click();
if(!await page.locator('#case-1').isVisible())throw Error('navigation');
await page.locator('#search').fill('nonexistent');
if(await page.locator('article.case:visible').count()!==0)throw Error('empty filter');
await page.locator('#search').fill('falling');
if(await page.locator('article.case:visible').count()!==1)throw Error('search');
await page.locator('#search').fill('');
await page.locator('#filter').selectOption('Inconclusive');
if(await page.locator('.case-link:visible').count()!==2)throw Error('result filter');
await page.locator('#filter').selectOption('');
await page.locator('.case-link').first().click();
await page.locator('#note-0').fill('Review export check');
const downloaded=page.waitForEvent('download');await page.locator('#export').click();const download=await downloaded;if(download.suggestedFilename()!=='tollchat-review-notes.md')throw Error('export');
await page.locator('#note-0').fill('');
await page.setViewportSize({width:390,height:844});
if(await page.locator('html').evaluate(el=>el.scrollWidth > el.clientWidth))throw Error('mobile overflow');
if(errors.length)throw Error(errors.join('\n'));
console.log('PASS: 20-case cap, navigation, search, result filter, note export, mobile width, no JavaScript errors');
await browser.close();
