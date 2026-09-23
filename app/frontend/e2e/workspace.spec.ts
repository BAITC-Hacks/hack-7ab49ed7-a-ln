import { test, expect } from '@playwright/test';
import { GRAPH_THEME } from '../src/graph/theme';

test('analyst explores a run, a node, assistant and exports', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/runs');
  await expect(page.getByRole('heading', { name: 'Исследования', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Открыть исследование →' }).first().click();
  await expect(page.getByText('Сеть переводов', { exact: true })).toBeVisible();
  await page
    .getByRole('button', { name: /Открыть клиента/ })
    .first()
    .click();
  await expect(page.getByText('Основание гипотезы', { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/node=\d{18}/);
  await expect(page.locator('canvas.sigma-nodes')).toBeVisible();
  await page.waitForTimeout(GRAPH_THEME.cameraDuration);
  await page.screenshot({ path: 'test-results/selected-node.png' });
  await page.getByRole('button', { name: 'Помощник', exact: true }).click();
  await page.getByRole('textbox', { name: 'Ваш вопрос' }).fill('топ 5 консолидаторов');
  await page.getByRole('textbox', { name: 'Ваш вопрос' }).press('Control+Enter');
  await expect(page.getByText('Ответ по локальным правилам', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Показать на графе', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Вернуться к обзору ×' })).toBeVisible();
  await page.waitForTimeout(GRAPH_THEME.cameraDuration);
  await page.screenshot({ path: 'test-results/assistant-subgraph.png' });
  await page.getByRole('button', { name: '↓ Экспорт' }).click();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: /Роли клиентов/ }).click();
  expect((await download).suggestedFilename()).toBe('nodes_roles.csv');
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click();
  await page.getByRole('button', { name: 'Обзор', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Модель продолжения переводов' })).toBeVisible();
  expect(errors).toEqual([]);
});
test('uploads and polls through completion', async ({ page }) => {
  await page.goto('/runs');
  await page.getByLabel('Название', { exact: true }).fill('Проверка загрузки');
  await page.getByLabel('Файлы данных', { exact: true }).setInputFiles({
    name: 'input.zip',
    mimeType: 'application/zip',
    buffer: Buffer.from('synthetic fixture'),
  });
  await page.getByText('Параметры сбора данных', { exact: true }).click();
  const threshold = page.getByRole('spinbutton', { name: 'Порог перевода, ₸' });
  await threshold.fill('0');
  await page.getByRole('button', { name: 'Загрузить и запустить анализ' }).click();
  await expect(threshold).toBeFocused();
  expect(await threshold.evaluate((element: HTMLInputElement) => element.validity.rangeUnderflow)).toBe(true);
  await expect(page).toHaveURL(/\/runs$/);
  await threshold.fill('0.01');
  await page.getByRole('button', { name: 'Загрузить и запустить анализ' }).click();
  await expect(page.getByRole('heading', { name: 'Проверка загрузки' })).toBeVisible();
  await expect(page.getByText('Сеть переводов', { exact: true })).toBeVisible({ timeout: 15000 });
});
for (const width of [1280, 1920])
  test(`layout fits ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto('/runs/00000000-0000-4000-8000-000000000001');
    await expect(page.getByText('Сеть переводов', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/workspace-${width}.png`, fullPage: true });
  });
