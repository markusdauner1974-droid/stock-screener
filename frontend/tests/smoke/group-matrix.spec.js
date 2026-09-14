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
  await tile.hover();
  await expect(page.getByRole('tooltip')).toContainText('Classification source');
  await tile.focus();
  await expect(page.getByRole('tooltip')).toContainText('Stock RS');
  await page.screenshot({path:testInfo.outputPath('stock-inspector-desktop.png')});
  await page.keyboard.press('Escape');
  await expect(page.getByRole('tooltip')).toBeHidden();
  await page.keyboard.press('Enter');
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


test('crowded Grid previews fit their rows on desktop and mobile', async ({page}, testInfo) => {
  await installMatrixFixtures(page, {mode:testInfo.project.name});
  const payload = matrixFixture('US',120);
  payload.stocks.forEach(stock => { stock.cap_tier = 'mid'; stock.market_cap_usd = 3e9; });
  payload.coverage.unknown_cap_count = 0;
  await page.route(url => url.pathname.endsWith('/groups/matrix') || url.pathname.endsWith('/groups_matrix.json'), route => route.fulfill({json:payload}));
  await page.setViewportSize({width:1440,height:1100});
  await page.goto(testInfo.project.name === 'static' ? '/#/groups' : '/groups');
  await page.getByRole('tab', {name:'Matrix'}).click();
  for (const width of [1440,390]) {
    await page.setViewportSize({width,height:1100});
    const more = page.getByRole('button', {name:/\+38 more in/}).first();
    await more.scrollIntoViewIfNeeded();
    await expect(more).toBeVisible();
    const bounds = await more.evaluate(button => ({bottom:button.getBoundingClientRect().bottom, rowBottom:button.parentElement.parentElement.parentElement.getBoundingClientRect().bottom}));
    expect(bounds.bottom).toBeLessThanOrEqual(bounds.rowBottom);
  }
});

test('Clusters form round bubble packs with stock inspection and complete overflow lists', async ({page}, testInfo) => {
  await installMatrixFixtures(page, {mode:testInfo.project.name});
  const payload = matrixFixture('US',600);
  payload.stocks.forEach((stock, i) => {
    stock.sector = 'Technology'; stock.ibd_industry_group = 'Computer-Software';
    const colorGroup = Math.floor(i / 6) % 3;
    stock.price_change_1d = i % 11 ? [-3,0,3][colorGroup] : null;
    stock.price_change_1w = i % 11 ? [-6,0,6][colorGroup] : null;
    stock.price_change_1m = i % 11 ? [-12,0,12][colorGroup] : null;
    stock.rs_rating = i % 11 ? [90,50,10][colorGroup] : null;
    const fraction = (i % 17) / 16;
    stock.market_cap_usd = [1e10 + 3e12 * fraction ** 3, 2e9 + 7e9 * fraction, 3e8 + 1.6e9 * fraction,
      5e7 + 2.4e8 * fraction, 1e6 + 4.8e7 * fraction, null][i % 6];
  });
  await page.route(url => url.pathname.endsWith('/groups/matrix') || url.pathname.endsWith('/groups_matrix.json'), route => route.fulfill({json:payload}));
  await page.setViewportSize({width:1440,height:1100});
  await page.goto(testInfo.project.name === 'static' ? '/#/groups' : '/groups');
  await page.getByRole('tab', {name:'Matrix'}).click();
  await page.getByRole('button', {name:'Clusters',exact:true}).click();
  const pack = page.locator('.group-matrix-bubble-pack').first();
  await expect(pack.locator('button')).toHaveCount(64);
  const circles = await pack.locator('button').evaluateAll(buttons => buttons.map(button => {
    const rect = button.getBoundingClientRect();
    return {x:rect.x + rect.width / 2, y:rect.y + rect.height / 2, width:rect.width, height:rect.height, radius:getComputedStyle(button).borderRadius};
  }));
  for (const [index, circle] of circles.entries()) {
    expect(circle.radius).toBe('50%');
    expect(Math.abs(circle.width - circle.height)).toBeLessThan(0.1);
    for (const other of circles.slice(index + 1)) {
      expect(Math.hypot(circle.x - other.x, circle.y - other.y) + 0.1).toBeGreaterThanOrEqual((circle.width + other.width) / 2);
    }
  }
  expect(Math.max(...circles.map(circle=>circle.width))).toBeGreaterThan(Math.min(...circles.map(circle=>circle.width)) * 2);
  const assertColorZones = async metric => {
    const positions = await pack.locator('button').evaluateAll(buttons => buttons.map(button => {
      const rect = button.getBoundingClientRect();
      const canvas = button.parentElement.getBoundingClientRect();
      return {symbol:button.dataset.matrixStock, distance:Math.hypot(rect.x + rect.width / 2 - canvas.x - canvas.width / 2,
        rect.y + rect.height / 2 - canvas.y - canvas.height / 2)};
    }));
    const meanDistance = value => {
      const matches = positions.filter(position => payload.stocks.find(stock=>stock.symbol === position.symbol)[metric] === value);
      return matches.reduce((sum, position)=>sum + position.distance,0) / matches.length;
    };
    const magnitude = {price_change_1d:3, price_change_1w:6, price_change_1m:12}[metric];
    const green = meanDistance(metric === 'rs_rating' ? 90 : magnitude);
    const neutral = meanDistance(metric === 'rs_rating' ? 50 : 0);
    const red = meanDistance(metric === 'rs_rating' ? 10 : -magnitude);
    expect(green).toBeLessThan(neutral);
    expect(neutral).toBeLessThan(red);
  };
  await assertColorZones('price_change_1d');
  await page.getByRole('combobox', {name:/^Color /}).click();
  await page.getByRole('option', {name:'Stock RS',exact:true}).click();
  await assertColorZones('rs_rating');
  await page.screenshot({path:testInfo.outputPath('bubble-clusters-rs-desktop.png'),fullPage:true});
  for (const [metric,label] of [['price_change_1w','1-Week Change'], ['price_change_1m','1-Month Change']]) {
    await page.getByRole('combobox', {name:/^Color /}).click();
    await page.getByRole('option', {name:label,exact:true}).click();
    await assertColorZones(metric);
    await page.getByRole('button', {name:'Grid',exact:true}).click();
    await expect(page.locator('[data-matrix-stock]:visible').first()).toHaveAttribute('aria-label', /%/);
    await page.getByRole('button', {name:'Clusters',exact:true}).click();
  }
  await page.getByRole('combobox', {name:/^Color /}).click();
  await page.getByRole('option', {name:'1-Day Change',exact:true}).click();
  const bubble = pack.locator('button').first();
  await bubble.hover();
  await expect(page.getByRole('tooltip')).toContainText('Classification source');
  await bubble.focus();
  await page.keyboard.press('Escape');
  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog')).toContainText('Stock RS');
  await page.keyboard.press('Escape');
  await page.getByRole('button', {name:/\+36 more in/}).first().click();
  await expect(page.getByRole('dialog')).toContainText('100 stocks');
  await page.keyboard.press('Escape');
  await page.mouse.move(0,0);
  await page.screenshot({path:testInfo.outputPath('bubble-clusters-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(bubble).toBeVisible();
  await page.screenshot({path:testInfo.outputPath('bubble-clusters-mobile.png'),fullPage:true});
});
