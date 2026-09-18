# Пробы

Готовые скрипты для `javascript_tool`. Каждый возвращает JSON. Вставлять целиком.

Все пробы только читают состояние страницы. Ничего не отправляют и не меняют.

---

## Проба 1 — Горизонтальный скролл и виновники

Главная проверка мобильной вёрстки. Запускать после `resize_window {preset: "mobile"}`
и перезагрузки страницы.

```js
(() => {
  const d = document.documentElement;
  const vw = d.clientWidth;
  const hasScroll = d.scrollWidth > vw;
  // Элемент внутри контейнера с обрезкой по X за вьюпорт не вылезает —
  // это карусель, бегущая строка или слайдер, а не дефект вёрстки
  const clipped = el => {
    let n = el.parentElement;
    while (n && n !== document.documentElement) {
      const ox = getComputedStyle(n).overflowX;
      if (ox === 'hidden' || ox === 'auto' || ox === 'scroll' || ox === 'clip') return true;
      n = n.parentElement;
    }
    return false;
  };
  const culprits = !hasScroll ? [] : [...document.querySelectorAll('body *')]
    .map(el => ({ el, r: el.getBoundingClientRect() }))
    .filter(({ el, r }) => r.width > 0 && (r.right > vw + 1 || r.left < -1) && !clipped(el))
    .sort((a, b) => b.r.right - a.r.right)
    .slice(0, 15)
    .map(({ el, r }) => ({
      tag: el.tagName.toLowerCase(),
      id: el.id || null,
      cls: (el.className || '').toString().trim().slice(0, 70) || null,
      left: Math.round(r.left),
      right: Math.round(r.right),
      text: (el.innerText || '').trim().slice(0, 40) || null
    }));
  return {
    viewport: vw,
    scrollWidth: d.scrollWidth,
    overflowPx: Math.max(0, d.scrollWidth - vw),
    hasHorizontalScroll: hasScroll,
    culprits
  };
})()
```

Виновник почти всегда самый правый элемент. Частые причины: фиксированная ширина в px,
длинное слово без переноса, отрицательный margin, `100vw` при видимом скроллбаре.

**Читать только `hasHorizontalScroll`.** Список виновников заполняется, лишь когда скролл
реально есть. Без этой проверки проба ловит любую карусель и бегущую строку: они выходят
за вьюпорт формально, но обрезаны родителем и страницу не расширяют. Проверено на живом
сайте — ложных срабатываний было десять из десяти.

---

## Проба 2 — Картинки: битые и без alt

```js
(() => {
  const imgs = [...document.images];
  const broken = imgs
    .filter(i => i.complete && i.naturalWidth === 0)
    .map(i => i.currentSrc || i.src);
  const noAlt = imgs
    .filter(i => !i.hasAttribute('alt') || !i.alt.trim())
    .map(i => ({ src: (i.currentSrc || i.src).slice(-80), w: i.width, h: i.height }));
  const decorative = imgs.filter(i => i.hasAttribute('alt') && !i.alt.trim()).length;
  return {
    total: imgs.length,
    brokenCount: broken.length,
    broken,
    noAltCount: noAlt.length,
    noAlt: noAlt.slice(0, 30),
    note: decorative + ' изображений с пустым alt="" — это допустимо для декоративных'
  };
})()
```

Битая картинка — всегда дефект. Отсутствие alt — P3, одной строкой, не по штуке.
Пустой `alt=""` у декоративных изображений корректен и дефектом не является.

---

## Проба 3 — Контраст по WCAG

Реальный расчёт коэффициента по относительной яркости, а не «на глаз».
Запускать отдельно в тёмной и в светлой теме.

```js
(() => {
  const lum = c => {
    const m = (c || '').match(/[\d.]+/g);
    if (!m || m.length < 3) return null;
    const [r, g, b] = m.slice(0, 3).map(Number).map(v => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const bgOf = el => {
    let n = el;
    while (n && n !== document.documentElement) {
      const bg = getComputedStyle(n).backgroundColor;
      if (bg && !/^rgba\(0,\s*0,\s*0,\s*0\)$|transparent/.test(bg)) return bg;
      n = n.parentElement;
    }
    return getComputedStyle(document.body).backgroundColor || 'rgb(255,255,255)';
  };
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el.children.length) continue;
    const txt = (el.innerText || '').trim();
    if (!txt) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || parseFloat(s.opacity) === 0) continue;
    const L1 = lum(s.color), L2 = lum(bgOf(el));
    if (L1 === null || L2 === null) continue;
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const size = parseFloat(s.fontSize);
    const large = size >= 24 || (size >= 18.66 && parseInt(s.fontWeight) >= 700);
    const need = large ? 3 : 4.5;
    if (ratio < need) {
      out.push({
        text: txt.slice(0, 45),
        ratio: +ratio.toFixed(2),
        need,
        color: s.color,
        bg: bgOf(el),
        fontSize: size,
        sel: el.tagName.toLowerCase() + (el.className ? '.' + el.className.toString().trim().split(/\s+/)[0] : '')
      });
    }
  }
  return { failing: out.length, theme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light', items: out.slice(0, 25) };
})()
```

Норма AA: 4.5 для обычного текста, 3 для крупного (24px+, либо 18.66px+ жирный).
Коэффициент около 1 — текст полностью сливается с фоном, это P1, а не P2.

---

## Проба 4 — Мелкие тапабельные элементы

Запускать на мобильной ширине. Порог 44×44 — минимум по рекомендациям Apple и WCAG 2.5.5.

```js
(() => {
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [onclick]';
  const small = [...document.querySelectorAll(sel)]
    .map(el => ({ el, r: el.getBoundingClientRect() }))
    .filter(({ el, r }) => {
      if (r.width === 0 || r.height === 0) return false;
      const s = getComputedStyle(el);
      if (s.visibility === 'hidden' || s.display === 'none') return false;
      return r.width < 44 || r.height < 44;
    })
    .slice(0, 25)
    .map(({ el, r }) => ({
      tag: el.tagName.toLowerCase(),
      text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 30),
      w: Math.round(r.width),
      h: Math.round(r.height)
    }));
  return { viewport: document.documentElement.clientWidth, count: small.length, items: small };
})()
```

---

## Проба 5 — Сбор внутренних ссылок

```js
(() => {
  const all = [...document.querySelectorAll('a[href]')];
  const internal = [...new Set(all.map(a => a.href).filter(h => h.startsWith(location.origin)))];
  const empty = all.filter(a => {
    const h = a.getAttribute('href');
    return !h || h === '#' || h.startsWith('javascript:void');
  }).length;
  return {
    totalLinks: all.length,
    internalUnique: internal.length,
    emptyOrHash: empty,
    links: internal
  };
})()
```

`emptyOrHash` — ссылки-заглушки. На готовом к релизу сайте их быть не должно.

---

## Проба 6 — Статусы внутренних ссылок

Запускать после пробы 5. HEAD с откатом на GET: часть серверов HEAD не поддерживает.

```js
(async () => {
  const links = [...new Set([...document.querySelectorAll('a[href]')]
    .map(a => a.href)
    .filter(h => h.startsWith(location.origin) && !h.includes('#')))].slice(0, 60);
  const broken = [];
  for (const u of links) {
    try {
      let r = await fetch(u, { method: 'HEAD', redirect: 'follow' });
      if (r.status === 405 || r.status === 501) {
        r = await fetch(u, { method: 'GET', redirect: 'follow' });
      }
      if (!r.ok) broken.push({ url: u, status: r.status });
    } catch (e) {
      broken.push({ url: u, status: 'ОШИБКА: ' + e.message });
    }
  }
  return { checked: links.length, brokenCount: broken.length, broken };
})()
```

Ограничено 60 ссылками, чтобы не подвешивать страницу. Для крупного сайта гонять постранично.

---

## Проба 7 — Структура документа

```js
(() => {
  const hs = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')]
    .map(h => ({ lvl: +h.tagName[1], text: (h.innerText || '').trim().slice(0, 50) }));
  const jumps = [];
  for (let i = 1; i < hs.length; i++) {
    if (hs[i].lvl - hs[i - 1].lvl > 1) {
      jumps.push({ from: 'h' + hs[i - 1].lvl, to: 'h' + hs[i].lvl, at: hs[i].text });
    }
  }
  return {
    lang: document.documentElement.lang || 'НЕ ЗАДАН',
    title: document.title || 'НЕ ЗАДАН',
    titleLength: document.title.length,
    description: document.querySelector('meta[name=description]')?.content?.slice(0, 120) || 'НЕТ',
    viewport: document.querySelector('meta[name=viewport]')?.content || 'НЕТ',
    h1Count: hs.filter(h => h.lvl === 1).length,
    headings: hs.slice(0, 20),
    levelJumps: jumps
  };
})()
```

`h1Count` должен быть 1. Отсутствие `lang` ломает экранные читалки и автоперевод.
Отсутствие meta viewport означает, что мобильной вёрстки нет вообще.

---

## Проба 8 — Инвентаризация форм

Только опись. Ничего не отправляет.

```js
(() => [...document.querySelectorAll('form')].map((f, i) => ({
  idx: i,
  action: f.getAttribute('action') || '(нет)',
  method: (f.getAttribute('method') || 'get').toUpperCase(),
  fields: [...f.querySelectorAll('input:not([type=hidden]), select, textarea')].map(el => ({
    name: el.name || el.id || '(без имени)',
    type: el.type || el.tagName.toLowerCase(),
    required: el.required,
    pattern: el.pattern || null,
    maxLength: el.maxLength > 0 ? el.maxLength : null
  })),
  submitText: (f.querySelector('[type=submit], button')?.innerText || '').trim()
})))()
```

Что смотреть дальше вручную: есть ли `required` там, где поле обязательно по смыслу;
проверяется ли формат email и телефона; появляется ли сообщение об ошибке и на каком языке.

---

## Проба 9 — Юридические страницы и cookie-баннер

```js
(() => {
  const words = ['оферт', 'политик', 'конфиденц', 'соглас', 'персональн', 'правил', 'услови', 'cookie', 'куки'];
  const links = [...document.querySelectorAll('a[href]')]
    .map(a => ({ text: (a.innerText || '').trim(), href: a.href }))
    .filter(l => l.text && words.some(w => l.text.toLowerCase().includes(w)));
  const banner = [...document.querySelectorAll('div,section,aside')]
    .filter(el => {
      const t = (el.innerText || '').toLowerCase();
      return (t.includes('cookie') || t.includes('куки')) && t.length < 600 && el.getBoundingClientRect().height > 0;
    })
    .slice(0, 2)
    .map(el => (el.innerText || '').trim().slice(0, 200));
  return { legalLinks: links, legalCount: links.length, cookieBannerVisible: banner.length > 0, bannerText: banner };
})()
```

Для российского сайта отсутствие политики обработки персональных данных — юридический
риск, а не косметика. Ставить P1, не P3.

---

## Проверка 404

Скриптом не делается — нужен переход:

```
navigate {url: "<origin>/__qa_probe_404__"}
```

Затем `get_page_text`. Правильно: осмысленная страница с понятным текстом и ссылкой
на главную. Неправильно: пустой экран, сырая ошибка сервера, молчаливый редирект
на главную (пользователь не понимает, что ссылка битая), страница с кодом 200.
