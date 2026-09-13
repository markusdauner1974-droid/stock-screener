import { expect, test } from '@playwright/test';
import { gzipSync } from 'node:zlib';
import { installMatrixFixtures, matrixFixture } from './groupMatrixFixtures';

test.beforeEach(async ({page}) => {
  page.matrixErrors = [];
  page.on('pageerror', error => page.matrixErrors.push(error.message));
});

test.afterEach(async ({page}) => { expect(page.matrixErrors).toEqual([]); });

test('both layouts, filters, stock drawer, keyboard and responsive themes', async ({page}, testInfo) => {
  const requests = await installMatrixFixtures(page, {mode:testInfo.project.name});
  await page.setViewportSize({width:1440,height:1100});
  await page.goto(testInfo.project.name === 'static' ? '/#/groups' : '/groups');
  await page.getByRole('tab', {name:'Matrix'}).click();
  await expect(page.getByRole('heading',{name:'US Stock Matrix'})).toBeVisible();
  await expect(page.locator('[data-matrix-stock]:visible').first()).toBeVisible();
  const tile = page.locator('[data-matrix-stock]:visible').first();
  await tile.focus(); await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('dialog').getByText('Stock RS',{exact:true})).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toBeHidden();
  await expect(tile).toBeFocused();
  await page.getByLabel('Search symbol or company').fill('US00001');
  await page.getByRole('button',{name:'Clusters',exact:true}).click();
  await expect(page.getByLabel('Search symbol or company')).toHaveValue('US00001');
  await expect(page.locator('[data-matrix-stock]:visible')).toHaveCount(1);
  await page.getByRole('button',{name:'Reset filters'}).click();
  await page.screenshot({path:testInfo.outputPath('clusters-dark-desktop.png'),fullPage:true});
  await page.getByRole('button',{name:'Grid',exact:true}).click();
  await page.screenshot({path:testInfo.outputPath('grid-dark-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await expect(page.locator('[data-matrix-stock]:visible').first()).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('grid-dark-mobile.png'),fullPage:true});
  const themeToggle = page.getByRole('button',{name:/light mode/i});
  if (await themeToggle.count()) await themeToggle.first().click();
  await page.screenshot({path:testInfo.outputPath('grid-light-mobile.png'),fullPage:true});
  if (testInfo.project.name === 'static') expect(requests.filter(p=>p.startsWith('/api/'))).toEqual([]);
});

test('large universe stays bounded and all overflow stocks remain reachable', async ({page}, testInfo) => {
  const payload = matrixFixture('US',10000);
  expect(gzipSync(JSON.stringify(payload)).length).toBeLessThan(2_000_000);
  await installMatrixFixtures(page,{count:10000,mode:testInfo.project.name});
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(testInfo.project.name === 'static' ? '/#/groups' : '/groups'); await page.getByRole('tab',{name:'Matrix'}).click();
  await expect(page.getByText(/10,000 shown/)).toBeVisible();
  expect(await page.locator('[data-matrix-stock]').count()).toBeLessThan(2000);
  const samples = [];
  for (let i=0;i<3;i++) {
    await page.evaluate(() => {
      const button = [...document.querySelectorAll('button')].find(el => el.textContent === 'Clusters');
      window.matrixPaintMs = null;
      button.addEventListener('click', () => {
        const start = performance.now();
        requestAnimationFrame(() => { window.matrixPaintMs = performance.now() - start; });
      }, {once:true});
    });
    await page.getByRole('button',{name:'Clusters',exact:true}).click();
    await expect(page.getByRole('region',{name:'Stock matrix clusters',exact:true})).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.matrixPaintMs)).not.toBeNull();
    samples.push(await page.evaluate(() => window.matrixPaintMs));
    expect(await page.locator('[data-matrix-stock]').count()).toBeLessThan(2000);
    await page.getByRole('button',{name:'Grid',exact:true}).click();
  }
  console.log('Matrix performance', testInfo.project.name, JSON.stringify({samples, compressedBytes:gzipSync(JSON.stringify(payload)).length, browser:await page.context().browser().version()}));
  await testInfo.attach('performance', {body:JSON.stringify({samples,compressedBytes:gzipSync(JSON.stringify(payload)).length,browser:await page.context().browser().version()}),contentType:'application/json'});
  await page.getByRole('button',{name:'View matching stocks'}).click();
  await expect(page.getByRole('dialog')).toContainText('10000 stocks');
  const list = page.getByRole('list',{name:'Matching stocks'});
  await list.evaluate(el=>{el.scrollTop=el.scrollHeight;});
  await expect(page.getByRole('button',{name:'Open US09999 details'})).toBeVisible();
});

test('market switching resets stock filters and preserves layout preferences', async ({page}, testInfo) => {
  await installMatrixFixtures(page,{mode:testInfo.project.name});
  await page.goto(testInfo.project.name === 'static' ? '/#/groups' : '/groups'); await page.getByRole('tab',{name:'Matrix'}).click();
  await expect(page.getByRole('heading',{name:'US Stock Matrix'})).toBeVisible();
  await page.getByLabel('Search symbol or company').fill('US00001');
  await page.getByRole('button',{name:'Clusters',exact:true}).click();
  const label = testInfo.project.name === 'static' ? 'Static market selector' : 'Market selector';
  await page.getByLabel(label,{exact:true}).click();
  await page.getByRole('option',{name:testInfo.project.name === 'static' ? /HK/ : /Hong Kong/}).click();
  await expect(page.getByRole('heading',{name:'HK Stock Matrix'})).toBeVisible();
  await expect(page.getByLabel('Search symbol or company')).toHaveValue('');
  await expect(page.getByRole('button',{name:'Clusters',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(page.locator('[data-matrix-stock]:visible').first()).toHaveText(/HK/);
  await expect(page.locator('[data-matrix-stock]:visible').filter({hasText:'US00001'})).toHaveCount(0);
});
