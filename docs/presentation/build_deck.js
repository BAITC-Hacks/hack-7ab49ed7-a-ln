// Презентация результатов «Граф денег» → docs/presentation/graph_money.pptx
// Запуск: NODE_PATH=<папка с node_modules/pptxgenjs> node docs/presentation/build_deck.js
// Скриншоты в img/ сняты с экрана приложения (uv run moneygraph serve) через Playwright.
const path = require("path");
const pptxgen = require("pptxgenjs");

const IMG = (f) => path.join(__dirname, "img", f);
const OUT = path.join(__dirname, "graph_money.pptx");

// ---------- палитра приложения: тёмно-синие «чернила», цвет — только у данных
const C = {
  ink: "19293A", ink2: "3D4E60", muted: "5D6B78", faint: "8C98A3", rule: "E1E6EA",
  plane: "EEF1F3", paper: "FFFFFF", navy2: "22384E", ice: "C9D6E3",
  coord: "E34948", cons: "EDA100", distr: "4A3AA7", transit: "2A78D6", term: "008300", periph: "A0A9B1",
  inflow: "1C5CAB", outflow: "EB6834", warnBg: "FBF4E2", warnInk: "6B5212",
};
const FONT = "Arial";
const W = 13.333, H = 7.5, M = 0.6;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.author = "Команда A-lN";
pres.company = "HackAlem AI";
pres.title = "Граф денег — кого проверять первым";

// ---------- помощники
const shadow = () => ({ type: "outer", color: "19293A", opacity: 0.14, blur: 8, offset: 2, angle: 90 });
function title(slide, text, opts = {}) {
  slide.addText(text, { x: M, y: 0.42, w: W - 2 * M, h: 0.8, fontFace: FONT, fontSize: 30, bold: true, color: opts.color || C.ink, margin: 0, isTextBox: true });
  if (opts.sub) slide.addText(opts.sub, { x: M, y: 1.18, w: W - 2 * M, h: 0.45, fontFace: FONT, fontSize: 15, color: opts.subColor || C.muted, margin: 0, isTextBox: true });
}
function shot(slide, file, x, y, w) {
  const h = w * 900 / 1600;
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x - 0.06, y: y - 0.06, w: w + 0.12, h: h + 0.12, rectRadius: 0.08, fill: { color: C.paper }, line: { color: C.rule, width: 1 }, shadow: shadow() });
  slide.addImage({ path: IMG(file), x, y, w, h });
  return h;
}
function dot(slide, color, x, y, d = 0.16) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color }, line: { color, width: 0 } });
}
function bullets(slide, items, x, y, w, h, size = 15) {
  slide.addText(items.map((t, i) => ({ text: t, options: { bullet: { indent: 16 }, breakLine: i < items.length - 1, paraSpaceAfter: 8 } })),
    { x, y, w, h, fontFace: FONT, fontSize: size, color: C.ink2, valign: "top", margin: 0, isTextBox: true });
}
function para(slide, runs, x, y, w, h, size = 15, color = C.ink2) {
  slide.addText(runs, { x, y, w, h, fontFace: FONT, fontSize: size, color, valign: "top", margin: 0, isTextBox: true, paraSpaceAfter: 6 });
}
function stat(slide, big, label, x, y, w, h = 1.35, color = C.ink, bg = C.plane) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.1, fill: { color: bg }, line: { color: bg, width: 0 } });
  slide.addText(big, { x: x + 0.25, y: y + 0.14, w: w - 0.4, h: 0.72, fontFace: FONT, fontSize: big.length > 7 ? 26 : 34, bold: true, color, margin: 0, isTextBox: true, valign: "middle" });
  slide.addText(label, { x: x + 0.25, y: y + 0.86, w: w - 0.4, h: h - 0.94, fontFace: FONT, fontSize: 12, color: C.muted, margin: 0, isTextBox: true, valign: "top" });
}
function card(slide, head, body, x, y, w, h, accent) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.1, fill: { color: C.paper }, line: { color: C.rule, width: 1 }, shadow: shadow() });
  if (accent) dot(slide, accent, x + 0.25, y + 0.3, 0.18);
  slide.addText(head, { x: x + (accent ? 0.55 : 0.25), y: y + 0.2, w: w - (accent ? 0.75 : 0.45), h: 0.4, fontFace: FONT, fontSize: 15, bold: true, color: C.ink, margin: 0, isTextBox: true, valign: "middle" });
  if (body) slide.addText(body, { x: x + 0.25, y: y + 0.68, w: w - 0.45, h: h - 0.82, fontFace: FONT, fontSize: 13.5, color: C.ink2, margin: 0, isTextBox: true, valign: "top" });
}
function footer(slide, n, dark = false) {
  slide.addText(String(n), { x: W - M - 0.5, y: H - 0.45, w: 0.5, h: 0.3, fontFace: FONT, fontSize: 10, color: dark ? C.ice : C.faint, align: "right", margin: 0, isTextBox: true });
}
let n = 0;

// ================= 1. Титул
{
  const s = pres.addSlide(); n++;
  s.background = { color: C.ink };
  s.addImage({ path: IMG("hero_network.png"), x: 6.55, y: 1.05, w: 6.3, h: 6.3 * 590 / 830, transparency: 8 });
  s.addText("Граф денег", { x: M, y: 1.7, w: 6.2, h: 1.2, fontFace: FONT, fontSize: 56, bold: true, color: C.paper, margin: 0, isTextBox: true });
  s.addText("Кого из 2 248 клиентов проверять первым — и почему", { x: M, y: 2.95, w: 5.8, h: 1.1, fontFace: FONT, fontSize: 22, color: C.ice, margin: 0, isTextBox: true, valign: "top" });
  s.addText("Восстановление финансовой структуры по сети внутрибанковских переводов", { x: M, y: 4.2, w: 5.6, h: 0.8, fontFace: FONT, fontSize: 14, color: C.faint, margin: 0, isTextBox: true, valign: "top" });
  s.addText("HackAlem AI, кейс «Граф денег»\nКоманда A-lN", { x: M, y: 6.2, w: 5.5, h: 0.7, fontFace: FONT, fontSize: 13, color: C.ice, margin: 0, isTextBox: true, valign: "bottom" });
  s.addNotes("Одной фразой: инструмент за 10 секунд превращает выгрузку переводов от 81 известного участника в очередь проверки из 50 клиентов, у каждого — роль и обоснование с числами.");
}

// ================= 2. Задача
{
  const s = pres.addSlide(); n++;
  title(s, "Задача", { sub: "AML-аналитику известен только нижний уровень цепочки — нужно восстановить остальное" });
  bullets(s, [
    "Правоохранительные органы передали банку 81 клиента, связанного с незаконным оборотом наркотиков.",
    "Кто собирает их деньги, через кого прогоняет и кто распоряжается — сейчас восстанавливается вручную: часы на один узел.",
    "Нужно: роль и обоснование для каждого клиента, кластеры с гипотезами, приоритет проверки и схема сети.",
    "Выводы — гипотезы для проверки, а не утверждение о виновности.",
  ], M, 1.95, 6.0, 4.6, 16);
  const x0 = 7.25, gw = 2.62;
  stat(s, "81", "исходных клиентов (seed) из дела", x0, 1.95, gw);
  stat(s, "2 248", "клиентов в графе на 4 колена", x0 + gw + 0.2, 1.95, gw);
  stat(s, "3 119", "связей, 4 840 переводов", x0, 3.5, gw);
  stat(s, "365,9 млн ₸", "оборот за июль 2026", x0 + gw + 0.2, 3.5, gw);
  s.addText("Все данные обезличены: только номер клиента, суммы и даты переводов.", { x: x0, y: 5.1, w: 2 * gw + 0.2, h: 0.5, fontFace: FONT, fontSize: 12, color: C.muted, margin: 0, isTextBox: true });
  footer(s, n);
  s.addNotes("Главный вопрос кейса — «кого из 2 248 клиентов смотреть первым и почему». Всё остальное подчинено ему.");
}

// ================= 3. Данные: что видно и чего нет
{
  const s = pres.addSlide(); n++;
  title(s, "Данные: что видно, а чего нет", { sub: "Особенности выгрузки учтены в правилах и попадают в обоснование каждого клиента" });
  const cw = 3.85, ch = 1.95, gx = 0.26, gy = 0.3, y1 = 2.0;
  const items = [
    ["Обрыв на 4-м колене", "У 444 клиентов исходящие просто не выгружались. Не называем их «конечными»: роль ставим по похожим клиентам колен 1–3."],
    ["Входящие видны частично", "Видны только плательщики из выборки — у всех. «Отдал больше, чем получил» — это невидимые входящие, а не аномалия."],
    ["Сумма ≠ количество", "Один перевод на 4 млн и сорок по 100 тыс. — разное поведение. Правила учитывают контрагентов, переводы и суммы."],
    ["Граф направленный", "Роли и метрики — с учётом направления денег. Кластеризация без направления оговорена явно."],
    ["Обрыв по времени", "Деньги, пришедшие 30–31 июля, могли уйти в августе — уверенность в роли снижается."],
    ["Порог 5 000 ₸, один банк, июль", "Дробление ниже порога, наличные и другие банки не видны — формируем список запросов данных."],
  ];
  items.forEach(([h, b], i) => card(s, h, b, M + (i % 3) * (cw + gx), y1 + Math.floor(i / 3) * (ch + gy), cw, ch, null));
  footer(s, n);
  s.addNotes("Организаторы назвали четыре ловушки; пятую — обрыв по времени — мы нашли сами. Все они видны в карточке клиента.");
}

// ================= 4. Решение: конвейер
{
  const s = pres.addSlide(); n++;
  title(s, "Решение: от выгрузки до очереди проверки", { sub: "Одна команда uv run moneygraph — около 10 секунд на ноутбуке" });
  const steps = [
    ["Данные", "3 parquet-файла, проверка целостности: переводы сходятся с рёбрами"],
    ["Метрики", "Потоки, контрагенты, время, циклы, маршруты, оценка для 4-го колена"],
    ["Роли", "6 правил с порогами: роль, уверенность и обоснование с числами"],
    ["Кластеры и приоритет", "Louvain с гипотезами; приоритет — 5 прозрачных слагаемых"],
    ["Интерфейс", "Экран всей сети, карточка клиента, AI-ассистент, CSV по схеме ТЗ"],
  ];
  const bw = 2.2, gap = 0.28, y = 2.35;
  steps.forEach(([h, b], i) => {
    const x = M + i * (bw + gap);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: bw, h: 3.0, rectRadius: 0.1, fill: { color: i === 2 ? C.ink : C.plane }, line: { color: i === 2 ? C.ink : C.plane, width: 0 } });
    s.addShape(pres.shapes.OVAL, { x: x + 0.25, y: y + 0.25, w: 0.55, h: 0.55, fill: { color: i === 2 ? C.paper : C.ink }, line: { color: i === 2 ? C.paper : C.ink, width: 0 } });
    s.addText(String(i + 1), { x: x + 0.25, y: y + 0.25, w: 0.55, h: 0.55, fontFace: FONT, fontSize: 18, bold: true, color: i === 2 ? C.ink : C.paper, align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText(h, { x: x + 0.25, y: y + 0.98, w: bw - 0.45, h: 0.75, fontFace: FONT, fontSize: 17, bold: true, color: i === 2 ? C.paper : C.ink, margin: 0, isTextBox: true, valign: "top" });
    s.addText(b, { x: x + 0.25, y: y + 1.75, w: bw - 0.45, h: 1.15, fontFace: FONT, fontSize: 12, color: i === 2 ? C.ice : C.ink2, margin: 0, isTextBox: true, valign: "top" });
    if (i < steps.length - 1) s.addText("→", { x: x + bw - 0.02, y: y + 1.2, w: gap + 0.04, h: 0.5, fontFace: FONT, fontSize: 18, color: C.faint, align: "center", margin: 0, isTextBox: true });
  });
  s.addText("На выходе: nodes_roles.csv (2 248 строк), clusters.csv, top_nodes.csv + маршруты, циклы, устойчивость сети и список запросов данных", { x: M, y: 5.8, w: W - 2 * M, h: 0.6, fontFace: FONT, fontSize: 13, color: C.muted, margin: 0, isTextBox: true });
  footer(s, n);
  s.addNotes("Ключевой шаг — роли: формальные правила с порогами, без обучаемой модели. Поэтому любую роль можно объяснить за минуту.");
}

// ================= 5. Роли
{
  const s = pres.addSlide(); n++;
  title(s, "Роли: формальные правила, а не чёрный ящик", { sub: "Правила проверяются сверху вниз, срабатывает первое; в карточке видно правило и числа" });
  const roles = [
    [C.coord, "Координатор", "", "Собирает от ≥8 и раздаёт ≥20; или платит ≥3 seed; или мост между группами"],
    [C.cons, "Консолидатор", "funnel account (воронка)", "≥4 разных плательщика или ≥2 seed среди плательщиков"],
    [C.distr, "Распределитель", "fan-out payouts", "≥10 получателей, и их втрое больше, чем плательщиков"],
    [C.transit, "Транзит", "pass-through / money mule layering", "Деньги уходят дальше: ≥50% полученного или ≥80% за 2 дня"],
    [C.term, "Конечный получатель", "", "Дальше ушло ≤10%, сумма от 30 тыс ₸ или ≥2 перевода"],
    [C.periph, "Периферия", "", "Признаков роли не выявлено"],
  ];
  const rx = M, rw = 7.0, rh = 0.74, y0 = 1.9;
  roles.forEach(([col, name, typ, rule], i) => {
    const y = y0 + i * (rh + 0.06);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: rx, y, w: rw, h: rh, rectRadius: 0.08, fill: { color: i % 2 ? C.paper : C.plane }, line: { color: i % 2 ? C.rule : C.plane, width: 1 } });
    dot(s, col, rx + 0.22, y + rh / 2 - 0.09, 0.18);
    s.addText([{ text: name, options: { bold: true, color: C.ink, breakLine: !!typ } }].concat(typ ? [{ text: typ, options: { fontSize: 11, color: C.muted } }] : []),
      { x: rx + 0.55, y: y + 0.06, w: 2.45, h: rh - 0.12, fontFace: FONT, fontSize: 14, valign: "middle", margin: 0, isTextBox: true });
    s.addText(rule, { x: rx + 3.1, y: y + 0.06, w: rw - 3.25, h: rh - 0.12, fontFace: FONT, fontSize: 12, color: C.ink2, valign: "middle", margin: 0, isTextBox: true });
  });
  s.addChart(pres.charts.BAR, [{ name: "Клиентов", labels: roles.map(r => r[1]), values: [17, 85, 44, 419, 978, 705] }], {
    x: 7.95, y: 1.75, w: 4.8, h: 4.95, barDir: "bar", chartColors: [C.ink], catAxisOrientation: "maxMin",
    showTitle: true, title: "Клиентов в каждой роли", titleFontFace: FONT, titleFontSize: 13, titleColor: C.ink,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontFace: FONT, dataLabelFontSize: 11, dataLabelColor: C.ink2,
    catAxisLabelFontFace: FONT, catAxisLabelFontSize: 11, catAxisLabelColor: C.ink2, valAxisHidden: true,
    valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false, barGapWidthPct: 60,
  });
  s.addText("Уверенность в роли: 0,5 на пороге правила, 1,0 при многократном превышении. На экране — словами: сильно, умеренно, слабо.", { x: M, y: 6.72, w: 7.0, h: 0.5, fontFace: FONT, fontSize: 11.5, color: C.muted, margin: 0, isTextBox: true });
  footer(s, n);
  s.addNotes("Роли — из словаря ТЗ; рядом — названия типологий AML. Цвет точки на схеме — это роль.");
}

// ================= 6. Приоритет
{
  const s = pres.addSlide(); n++;
  title(s, "Приоритет: кого смотреть первым", { sub: "Число от 0 до 1 — сумма пяти понятных слагаемых; очередь — все клиенты по убыванию" });
  s.addChart(pres.charts.BAR, [{ name: "Максимальный вклад", labels: ["Роль и уверенность", "Оборот", "Центральность", "Связь с seed", "Сигналы"], values: [0.35, 0.25, 0.2, 0.1, 0.1] }], {
    x: M - 0.1, y: 1.8, w: 6.3, h: 3.55, barDir: "bar", chartColors: [C.ink], catAxisOrientation: "maxMin",
    showTitle: true, title: "Максимальный вклад слагаемого", titleFontFace: FONT, titleFontSize: 13, titleColor: C.ink,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00", dataLabelFontFace: FONT, dataLabelFontSize: 11, dataLabelColor: C.ink2,
    catAxisLabelFontFace: FONT, catAxisLabelFontSize: 12, catAxisLabelColor: C.ink2, valAxisHidden: true, valAxisMaxVal: 0.42,
    valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false, barGapWidthPct: 55,
  });
  bullets(s, [
    "Вес роли: координатор 1,0 — консолидатор 0,9 — распределитель 0,8 — транзит 0,6 — конечный 0,5 — периферия 0,1.",
    "Исходные клиенты × 0,9: они уже известны, инструмент ищет новых.",
    "На экране: место в очереди и уровень — высокий №1–50, средний №51–200, низкий — остальные.",
  ], M, 5.5, 6.1, 1.6, 12.5);
  // пример №1
  const x = 7.2, w = 5.55;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.85, w, h: 4.2, rectRadius: 0.1, fill: { color: C.plane }, line: { color: C.plane, width: 0 } });
  s.addText("Пример: №1 в очереди", { x: x + 0.3, y: 2.05, w: w - 0.6, h: 0.4, fontFace: FONT, fontSize: 15, bold: true, color: C.ink, margin: 0, isTextBox: true });
  s.addText("…8165763100, консолидатор", { x: x + 0.3, y: 2.45, w: w - 0.6, h: 0.35, fontFace: FONT, fontSize: 12, color: C.muted, margin: 0, isTextBox: true });
  const parts = [["роль", "0,9 × 1,00 × 0,35", "0,315"], ["оборот", "больше, чем у ~98% клиентов", "0,244"], ["центральность", "PageRank, посредничество", "0,194"], ["связь с seed", "1 seed среди плательщиков", "0,033"], ["сигналы", "3 и больше", "0,100"]];
  parts.forEach(([a, b, v], i) => {
    const y = 2.95 + i * 0.5;
    s.addText(a, { x: x + 0.3, y, w: 1.55, h: 0.4, fontFace: FONT, fontSize: 13, bold: true, color: C.ink, margin: 0, isTextBox: true, valign: "middle" });
    s.addText(b, { x: x + 1.85, y, w: 2.7, h: 0.4, fontFace: FONT, fontSize: 12, color: C.ink2, margin: 0, isTextBox: true, valign: "middle" });
    s.addText(v, { x: x + w - 1.1, y, w: 0.8, h: 0.4, fontFace: FONT, fontSize: 13, color: C.ink, margin: 0, isTextBox: true, align: "right", valign: "middle" });
  });
  s.addShape(pres.shapes.LINE, { x: x + 0.3, y: 5.5, w: w - 0.6, h: 0, line: { color: C.faint, width: 1 } });
  s.addText([{ text: "= 0,89", options: { bold: true, fontSize: 22, color: C.ink } }, { text: "   №1 из 2 248, высокий приоритет", options: { fontSize: 13, color: C.muted } }], { x: x + 0.3, y: 5.55, w: w - 0.6, h: 0.45, fontFace: FONT, margin: 0, isTextBox: true, valign: "middle" });
  s.addText("Устойчивость: изменение любого веса на ±20% сохраняет ≥85% топ-20 (в среднем 93%).", { x, y: 6.2, w, h: 0.5, fontFace: FONT, fontSize: 12, color: C.muted, margin: 0, isTextBox: true });
  footer(s, n);
  s.addNotes("Веса экспертные: размеченных ответов нет. Поэтому проверили устойчивость — порядок почти не меняется при изменении весов.");
}

// ================= 7. Результаты в цифрах
{
  const s = pres.addSlide(); n++;
  title(s, "Результаты в цифрах");
  const sx = M, sw = 2.75;
  const th = 1.55, ty = [1.5, 3.3, 5.1];
  stat(s, "17 из 20", "первых в очереди — новые клиенты, не из исходных 81", sx, ty[0], sw, th);
  stat(s, "74%", "оборота от seed отрезает изъятие топ-50; случайные 50 — лишь 5%", sx + sw + 0.2, ty[0], sw, th);
  stat(s, "72", "кластера с гипотезой назначения; в 9 — несколько seed", sx, ty[1], sw, th);
  stat(s, "380", "запросов данных: что запросить, по кому и почему", sx + sw + 0.2, ty[1], sw, th);
  stat(s, "~10 с", "полный пересчёт одной командой, схема ТЗ проверяется сама", sx, ty[2], sw, th);
  stat(s, "468", "возвратных циклов и 478 устойчивых маршрутов A→B→C", sx + sw + 0.2, ty[2], sw, th);
  s.addChart(pres.charts.BAR, [
    { name: "Изъяты первые по приоритету", labels: ["5", "10", "20", "50"], values: [86.9, 83.5, 66.5, 26.3] },
    { name: "Изъяты случайные клиенты", labels: ["5", "10", "20", "50"], values: [99.8, 99.0, 98.3, 94.8] },
  ], {
    x: 6.75, y: 1.45, w: 6.0, h: 5.05, barDir: "col", barGrouping: "clustered", chartColors: [C.ink, C.periph],
    showTitle: true, title: "Оборот, достижимый от seed после изъятия N клиентов, %", titleFontFace: FONT, titleFontSize: 13, titleColor: C.ink,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0", dataLabelFontFace: FONT, dataLabelFontSize: 10, dataLabelColor: C.ink2,
    catAxisTitle: "Изъято клиентов", showCatAxisTitle: true, catAxisTitleFontSize: 11, catAxisTitleColor: C.muted,
    catAxisLabelFontFace: FONT, catAxisLabelFontSize: 11, catAxisLabelColor: C.ink2, valAxisHidden: true, valAxisMaxVal: 110, valAxisMinVal: 0,
    valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: true, legendPos: "b", legendFontFace: FONT, legendFontSize: 11, legendColor: C.ink2, barGapWidthPct: 70,
  });
  footer(s, n);
  s.addNotes("Самое сильное доказательство, что приоритет находит несущие узлы: изъятие 50 первых отрезает три четверти оборота, изъятие 50 случайных — почти ничего.");
}

// ================= 8. Экран аналитика
{
  const s = pres.addSlide(); n++;
  title(s, "Экран аналитика: вся сеть сразу", { sub: "Один HTML-файл, работает без интернета: 2 248 клиентов и 3 119 связей, цвет — роль" });
  const x = M, y = 1.85, w = 8.3;
  const h = shot(s, "01_overview.png", x, y, w);
  const notes = [
    ["1", "Очередь проверки", "Место в очереди и насколько ярко выражена роль. Наведение подсвечивает клиента на схеме."],
    ["2", "Вся сеть", "Размер точки — приоритет, толщина связи — сумма, кольцо — seed, бледная точка — 4-е колено."],
    ["3", "Карточка и AI-ассистент", "Роль, обоснование, потоки, контрагенты с датами; вопросы на обычном языке."],
  ];
  notes.forEach(([k, a, b], i) => {
    const yy = y + i * 1.5, xx = x + w + 0.45;
    s.addShape(pres.shapes.OVAL, { x: xx, y: yy + 0.02, w: 0.42, h: 0.42, fill: { color: C.ink }, line: { color: C.ink, width: 0 } });
    s.addText(k, { x: xx, y: yy + 0.02, w: 0.42, h: 0.42, fontFace: FONT, fontSize: 14, bold: true, color: C.paper, align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText(a, { x: xx + 0.58, y: yy, w: 2.8, h: 0.45, fontFace: FONT, fontSize: 15, bold: true, color: C.ink, margin: 0, isTextBox: true, valign: "middle" });
    s.addText(b, { x: xx + 0.58, y: yy + 0.47, w: 2.8, h: 0.95, fontFace: FONT, fontSize: 12, color: C.ink2, margin: 0, isTextBox: true, valign: "top" });
  });
  s.addText("Поиск по последним цифрам номера, фильтры по ролям, сумме и топ-N, страницы «Как считается приоритет» и «Как считается уверенность».", { x, y: y + h + 0.2, w: w, h: 0.4, fontFace: FONT, fontSize: 12, color: C.muted, margin: 0, isTextBox: true });
  footer(s, n);
  s.addNotes("Показываем живьём: uv run moneygraph serve, открыть 127.0.0.1:8765. Жюри называет номер — вводим последние цифры, клиент выделяется на схеме.");
}

// ================= 9–11. Кейсы
function caseSlide(head, sub, file, points, note) {
  const s = pres.addSlide(); n++;
  title(s, head, { sub });
  shot(s, file, 4.75, 1.9, 7.95);
  bullets(s, points, M, 1.95, 3.8, 5.0, 13.5);
  footer(s, n);
  s.addNotes(note);
}
caseSlide("Кейс 1. №1 в очереди — точка сбора", "…8165763100, консолидатор (funnel account), роль выражена сильно", "02_top1.png", [
  "Получает от 15 плательщиков 1,17 млн ₸ за 26 переводов; 4 из них заплатили в один день, 12 июля.",
  "Почти всё уходит дальше: 109% полученного, 54% — в течение 2 дней. Значит, есть поступления вне выборки.",
  "«Откуда пришли деньги»: 79 клиентов за 4 шага, среди них 6 seed.",
  "Синие связи — входящие, оранжевые — исходящие; остальная сеть приглушена.",
], "Кнопки «Откуда пришли деньги» и «Куда ушли деньги» подсвечивают цепочки на 4 шага — так видно, что к этой точке сходятся деньги нескольких известных участников.");
caseSlide("Кейс 2. Кластер 8 — скрытый узел раздачи", "126 клиентов, ни одного seed: эту часть сети без инструмента не видно", "05_cluster8.png", [
  "Хаб …8603629100 собрал 1,82 млн ₸ от 19 плательщиков и раздал 4,99 млн ₸ 61 получателю; всё ушло дальше за 2 дня.",
  "Петля: хаб → …1857829100 → …3880331100 → снова хаб — признак многослойного прогона.",
  "В кластер входит 2,98 млн ₸, выходит 5,28 млн ₸, внутри — 14,79 млн ₸.",
  "Гипотеза: точка выплат участникам или обналичивания.",
], "Синие связи — деньги входят в кластер, оранжевые — выходят, тёмные — движутся внутри. Кластер находится в 2–4 шагах от известных участников.");
caseSlide("Кейс 3. 4-е колено — ловушка обрыва", "…5075949100 получил 2,23 млн ₸, исходящих в данных нет", "06_trunc.png", [
  "Наивный вывод «деньги осели» неверен: исходящие 4-го колена просто не выгружались.",
  "Смотрим на похожих клиентов колен 1–3: с таким профилем 57% пересылают деньги дальше.",
  "Роль — вероятный транзит, уверенность слабая, приоритет низкий (№332).",
  "Клиент попадает в список запросов: выписка исходящих за июль–август.",
], "Проверили оценку честно: бэктест «колена 1–2 → колено 3» даёт AUC 0,58 — сигнал слабый, поэтому уверенность умеренная и нужен запрос выписки.");

// ================= 12. AI-ассистент
{
  const s = pres.addSlide(); n++;
  title(s, "AI-ассистент: вопрос словами — ответ по графу", { sub: "Отвечает только по результатам расчёта, со ссылками на конкретных клиентов" });
  shot(s, "07_ai.png", M, 1.9, 7.95);
  bullets(s, [
    "Языковая модель (OpenAI) вызывает инструменты над результатами расчёта: карточка, контрагенты, топ по ролям, кластер, пути, общие получатели.",
    "Каждое утверждение — с номером клиента и числами; формулировки — гипотезы.",
    "Упомянутые клиенты сразу подсвечиваются на схеме.",
    "Пути, источники денег и общие получатели считаются прямо в браузере, без сети.",
  ], 8.95, 1.95, 3.8, 5.0, 13.5);
  footer(s, n);
  s.addNotes("Пример вопроса: «Почему этот клиент так высоко в очереди и кого проверить рядом?». Провайдер модели отделён — можно подключить другую.");
}

// ================= 13. Объяснимость
{
  const s = pres.addSlide(); n++;
  title(s, "Объяснимость: каждое число можно разобрать", { sub: "Отдельные страницы в приложении; пороги и веса берутся из того же файла настроек, что и расчёт" });
  const w = 5.85;
  shot(s, "08_priority_page.png", M, 1.95, w);
  shot(s, "09_confidence_page.png", M + w + 0.35, 1.95, w);
  s.addText("Как считается приоритет: вклад пяти слагаемых на живых примерах", { x: M, y: 5.45, w, h: 0.5, fontFace: FONT, fontSize: 13, bold: true, color: C.ink, margin: 0, isTextBox: true });
  s.addText("Как считается уверенность: правило для каждой роли и график по консолидаторам", { x: M + w + 0.35, y: 5.45, w, h: 0.5, fontFace: FONT, fontSize: 13, bold: true, color: C.ink, margin: 0, isTextBox: true });
  s.addText("В карточке любого клиента — сработавшее правило с числами и ссылки «как считается».", { x: M, y: 6.1, w: W - 2 * M, h: 0.45, fontFace: FONT, fontSize: 12, color: C.muted, margin: 0, isTextBox: true });
  footer(s, n);
  s.addNotes("Жюри называет три номера — для каждого за минуту показываем правило, числа и разложение приоритета.");
}

// ================= 14. Архитектура и воспроизводимость
{
  const s = pres.addSlide(); n++;
  title(s, "Архитектура и воспроизводимость", { sub: "Лёгкий проект: нужен только uv — он сам ставит Python 3.12 и пакеты" });
  const box = (x, y, w, h, head, body, dark) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.1, fill: { color: dark ? C.ink : C.plane }, line: { color: dark ? C.ink : C.plane, width: 0 } });
    s.addText(head, { x: x + 0.2, y: y + 0.15, w: w - 0.4, h: 0.4, fontFace: FONT, fontSize: 14, bold: true, color: dark ? C.paper : C.ink, margin: 0, isTextBox: true });
    s.addText(body, { x: x + 0.2, y: y + 0.58, w: w - 0.4, h: h - 0.7, fontFace: FONT, fontSize: 11.5, color: dark ? C.ice : C.ink2, margin: 0, isTextBox: true, valign: "top" });
  };
  const arrow = (x, y) => s.addText("→", { x, y, w: 0.45, h: 0.5, fontFace: FONT, fontSize: 20, color: C.faint, align: "center", margin: 0, isTextBox: true });
  box(M, 2.0, 2.5, 1.55, "data/*.parquet", "2 248 клиентов, 3 119 связей, 4 840 переводов");
  arrow(M + 2.55, 2.5);
  box(M + 3.05, 2.0, 3.0, 1.55, "Конвейер moneygraph", "Python: pandas, networkx, igraph. Роли, кластеры, приоритет, проверка схемы ТЗ", true);
  arrow(M + 6.1, 2.5);
  box(M + 6.6, 2.0, 2.7, 1.55, "out/", "3 CSV по схеме ТЗ, graph.json, viewer.html, доп. выгрузки");
  arrow(M + 9.35, 2.5);
  box(M + 9.85, 2.0, 2.28, 1.55, "Браузер", "Экран офлайн, двойной клик по viewer.html");
  box(M + 6.6, 3.95, 5.53, 1.2, "moneygraph serve (необязательно)", "Тот же экран + /api/ask: AI-ассистент через OpenAI, ключ хранится только в .env");
  bullets(s, [
    "Установка одной командой: ./install.sh (Linux, macOS); инструкция для любой ОС — INSTALL.md.",
    "Детерминированно: повторный прогон с чистой машины даёт те же CSV байт в байт.",
    "7 автотестов: схема ТЗ, обоснования с числами, 4-е колено, нет захардкоженных номеров.",
  ], M, 3.95, 5.8, 2.6, 13);
  footer(s, n);
  s.addNotes("Бэкенд — пакетный Python-конвейер, фронтенд — один статический HTML с данными внутри. Сервер нужен только для языковой модели.");
}

// ================= 15. Ограничения и масштабирование
{
  const s = pres.addSlide(); n++;
  title(s, "Ограничения и что дальше");
  const cw = 5.9;
  card(s, "Ограничения данных и метода", "", M, 1.5, cw, 3.55, null);
  bullets(s, [
    "Только внутрибанковские переводы от 5 000 ₸ за июль: наличные, другие банки и август не видны.",
    "Входящие видны частично, исходящие обрезаны на 4-м колене; оценка для 4-го колена — слабый сигнал (AUC 0,58).",
    "Пороги и веса экспертные: размеченных ролей нет, качество — в обоснованности, проверена устойчивость.",
    "Все выводы — гипотезы для проверки аналитиком.",
  ], M + 0.25, 2.2, cw - 0.5, 2.75, 13.5);
  card(s, "Масштабирование до ~1 млн клиентов", "", M + cw + 0.33, 1.5, cw, 3.55, null);
  bullets(s, [
    "Признаки — в DuckDB или Polars: суммы, степени и время считаются колоночными запросами.",
    "Графовые алгоритмы — igraph или graph-tool, приближённое посредничество, Leiden вместо Louvain.",
    "Инкрементальный пересчёт затронутых компонент; пороги в перцентилях.",
    "Экран получает окрестность клиента с сервера; ассистент работает через индексы базы.",
  ], M + cw + 0.58, 2.2, cw - 0.5, 2.75, 13.5);
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: M, y: 5.35, w: W - 2 * M, h: 1.35, rectRadius: 0.1, fill: { color: C.ink }, line: { color: C.ink, width: 0 } });
  s.addText("Следующий шаг для аналитика", { x: M + 0.3, y: 5.5, w: 5, h: 0.4, fontFace: FONT, fontSize: 15, bold: true, color: C.paper, margin: 0, isTextBox: true });
  s.addText("data_requests.csv — 380 запросов, чтобы подтвердить или снять гипотезы: выписки исходящих по 4-му колену, входящие из-за пределов выборки, операции за август, наличные по seed без переводов.", { x: M + 0.3, y: 5.92, w: W - 2 * M - 0.6, h: 0.7, fontFace: FONT, fontSize: 13, color: C.ice, margin: 0, isTextBox: true, valign: "top" });
  footer(s, n);
  s.addNotes("Следующий шаг для аналитика — data_requests.csv: 380 запросов, что и по кому запросить, чтобы подтвердить или снять гипотезы.");
}

// ================= 16. Итог
{
  const s = pres.addSlide(); n++;
  s.background = { color: C.ink };
  s.addText("Итог", { x: M, y: 0.6, w: 6, h: 0.8, fontFace: FONT, fontSize: 34, bold: true, color: C.paper, margin: 0, isTextBox: true });
  const items = [
    ["Очередь из 50 клиентов", "каждый с ролью, уверенностью и обоснованием с числами; 17 из 20 первых — новые"],
    ["Ловушки данных учтены", "4-е колено, неполные входящие, конец периода — прямо в правилах и карточке"],
    ["Экран, который отвечает на вопросы", "вся сеть, карточка, объяснения и AI-ассистент — в одном файле"],
    ["Воспроизводимо за 10 секунд", "одна команда, автотесты, одинаковый результат на любой машине"],
  ];
  items.forEach(([a, b], i) => {
    const y = 1.75 + i * 1.12;
    s.addShape(pres.shapes.OVAL, { x: M, y: y + 0.08, w: 0.26, h: 0.26, fill: { color: [C.coord, C.cons, C.transit, C.term][i] }, line: { color: C.ink, width: 0 } });
    s.addText(a, { x: M + 0.5, y, w: 7.2, h: 0.45, fontFace: FONT, fontSize: 19, bold: true, color: C.paper, margin: 0, isTextBox: true, valign: "middle" });
    s.addText(b, { x: M + 0.5, y: y + 0.45, w: 7.2, h: 0.5, fontFace: FONT, fontSize: 13, color: C.ice, margin: 0, isTextBox: true, valign: "top" });
  });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 8.55, y: 1.75, w: 4.18, h: 3.9, rectRadius: 0.12, fill: { color: C.navy2 }, line: { color: C.navy2, width: 0 } });
  s.addText("Запуск", { x: 8.85, y: 1.95, w: 3.6, h: 0.4, fontFace: FONT, fontSize: 15, bold: true, color: C.paper, margin: 0, isTextBox: true });
  s.addText([
    { text: "./install.sh", options: { fontFace: "Courier New", color: C.paper, breakLine: true } },
    { text: "установка и пересчёт", options: { color: C.faint, fontSize: 11, breakLine: true } },
    { text: " ", options: { fontSize: 6, breakLine: true } },
    { text: "uv run moneygraph serve", options: { fontFace: "Courier New", color: C.paper, breakLine: true } },
    { text: "экран и AI-ассистент на 127.0.0.1:8765", options: { color: C.faint, fontSize: 11, breakLine: true } },
    { text: " ", options: { fontSize: 6, breakLine: true } },
    { text: "out/viewer.html", options: { fontFace: "Courier New", color: C.paper, breakLine: true } },
    { text: "экран без сервера и интернета", options: { color: C.faint, fontSize: 11 } },
  ], { x: 8.85, y: 2.45, w: 3.7, h: 3.0, fontFace: FONT, fontSize: 13, margin: 0, isTextBox: true, valign: "top" });
  s.addText("Роли — гипотезы для проверки, а не вывод о виновности.", { x: M, y: 6.45, w: 8, h: 0.4, fontFace: FONT, fontSize: 12, color: C.faint, margin: 0, isTextBox: true });
  footer(s, n, true);
  s.addNotes("Спасибо. Готовы показать любого клиента, которого назовёт жюри.");
}

pres.writeFile({ fileName: OUT }).then(f => console.log("written", f));
