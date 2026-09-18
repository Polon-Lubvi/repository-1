# Пробы

Готовые скрипты для `javascript_tool`. Каждый возвращает JSON. Вставлять целиком.

Все пробы только читают состояние страницы. Ничего не отправляют и не меняют.

---

## Проба 0 — Годность замеров

**Запускать первой.** Если панель браузера свёрнута или скрыта, ширина вьюпорта равна
нулю, и пробы 1, 4 и 13 вернут бессмысленные числа, которые легко принять за находки.
Проверено на живом сайте: при скрытой панели проба 13 отрапортовала `viewport: 0`
и ширину документа 257px вместо реальной.

```js
(() => {
  const w = document.documentElement.clientWidth || window.innerWidth || 0;
  const h = document.documentElement.clientHeight || window.innerHeight || 0;
  return w > 0 && h > 0
    ? { годно: true, viewport: w + 'x' + h }
    : { годно: false, viewport: w + 'x' + h,
        причина: 'Панель браузера скрыта или свёрнута. Замеры вёрстки недостоверны — показать панель и повторить пробы 1, 4, 13.' };
})()
```

Пробы, не зависящие от размеров, — 2, 3, 5, 6, 7, 8, 9, 10, 11, 12 — работают и при
скрытой панели.

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

## Проба 10 — Доступные имена и ARIA

Кнопка-иконка без подписи для экранной читалки — просто «кнопка». Пользователь не знает,
что она делает.

```js
(() => {
  const accName = el => {
    const al = el.getAttribute('aria-label');
    if (al && al.trim()) return al.trim();
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = lb.split(/\s+/).map(id => document.getElementById(id)?.innerText || '').join(' ').trim();
      if (t) return t;
    }
    const txt = (el.innerText || '').trim();
    if (txt) return txt;
    const img = el.querySelector('img[alt]');
    if (img && img.alt.trim()) return img.alt.trim();
    const svgTitle = el.querySelector('svg title');
    if (svgTitle && svgTitle.textContent.trim()) return svgTitle.textContent.trim();
    const ttl = el.getAttribute('title');
    if (ttl && ttl.trim()) return ttl.trim();
    if (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA') {
      if (el.id) {
        const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
        if (l && l.innerText.trim()) return l.innerText.trim();
      }
      const wrap = el.closest('label');
      if (wrap && wrap.innerText.trim()) return wrap.innerText.trim();
      if (el.placeholder && el.placeholder.trim()) return 'ТОЛЬКО PLACEHOLDER: ' + el.placeholder.trim();
    }
    return null;
  };
  const VALID = new Set(['button','link','checkbox','radio','tab','tablist','tabpanel','dialog','navigation','banner','main','contentinfo','complementary','search','form','list','listitem','menu','menuitem','menubar','alert','alertdialog','status','img','presentation','none','region','article','heading','switch','tooltip','progressbar','separator','textbox','combobox','option','listbox','grid','row','cell','columnheader','rowheader','table','toolbar','group','radiogroup','tree','treeitem','feed','figure','note','document','application','timer','log','slider','spinbutton','scrollbar']);
  const nameless = [], badRole = [];
  const visible = el => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  for (const el of document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link]')) {
    if (!visible(el)) continue;
    const n = accName(el);
    if (!n || n.startsWith('ТОЛЬКО PLACEHOLDER')) {
      nameless.push({ tag: el.tagName.toLowerCase(), type: el.type || null, name: n, html: el.outerHTML.slice(0, 90) });
    }
  }
  for (const el of document.querySelectorAll('[role]')) {
    const role = (el.getAttribute('role') || '').trim().toLowerCase();
    if (role && !VALID.has(role)) badRole.push({ role, tag: el.tagName.toLowerCase() });
  }
  return { namelessCount: nameless.length, nameless: nameless.slice(0, 20), invalidRoleCount: badRole.length, invalidRoles: badRole.slice(0, 10) };
})()
```

Placeholder вместо подписи считается дефектом: он исчезает при вводе, и пользователь
теряет подсказку о том, что за поле он заполняет.

---

## Проба 11 — Видимость фокуса

Элемент, не меняющийся при фокусе, делает навигацию с клавиатуры невозможной: человек
не видит, где он находится.

**Проба разбирает стили статически, а не фокусирует элементы.** Это принципиально.
Ранняя версия вызывала `.focus()` программно и сравнивала стиль до и после — на живом
сайте она дала 37 ложных срабатываний из 37. Причина: современные сайты пишут стиль
фокуса на `:focus-visible`, который браузер применяет только при навигации с клавиатуры,
а не при программном вызове. Динамическая проверка здесь недостоверна в принципе.

```js
(() => {
  let focusVisible = 0, focusPlain = 0, cors = 0, readable = 0;
  const resets = [];
  for (const sh of document.styleSheets) {
    let rs;
    try { rs = sh.cssRules; readable++; } catch (e) { cors++; continue; }
    const walk = list => {
      for (const r of list) {
        if (r.selectorText) {
          if (/:focus-visible/.test(r.selectorText)) focusVisible++;
          else if (/:focus/.test(r.selectorText)) focusPlain++;
          // сброс контура вне контекста фокуса — подозрительно
          if (/outline\s*:\s*(none|0)\b/.test(r.cssText) && !/:focus/.test(r.selectorText)) {
            resets.push(r.selectorText.slice(0, 70));
          }
        }
        if (r.cssRules) walk(r.cssRules);
      }
    };
    walk(rs);
  }
  const total = focusVisible + focusPlain;
  return {
    focusVisibleRules: focusVisible,
    focusRules: focusPlain,
    totalFocusRules: total,
    outlineResets: resets.length,
    outlineResetSelectors: resets.slice(0, 8),
    corsBlockedSheets: cors,
    readableSheets: readable,
    verdict: total === 0
      ? (resets.length
          ? 'ДЕФЕКТ: outline сброшен, а правил фокуса нет — навигация с клавиатуры вслепую'
          : 'правил фокуса нет вообще — проверить Tab вручную')
      : 'правила фокуса есть: ' + focusVisible + ' на :focus-visible, ' + focusPlain + ' на :focus'
  };
})()
```

Дефект — только сочетание «`outline: none` есть, правил фокуса нет». Один лишь
`outline: none` при наличии `:focus-visible` — нормальная современная практика, багом
не является. Если `corsBlockedSheets` больше нуля, часть стилей недоступна и вывод
неполный: сказать об этом, а не делать вид, что проверено всё.

---

## Проба 12 — Уважение к prefers-reduced-motion

```js
(() => {
  let mediaBlocks = 0, rulesInside = 0, readable = 0, blocked = 0;
  for (const sh of document.styleSheets) {
    let rs;
    try { rs = sh.cssRules; readable++; } catch (e) { blocked++; continue; }
    const walk = list => {
      for (const r of list) {
        if (r.type === CSSRule.MEDIA_RULE) {
          const cond = r.conditionText || (r.media && r.media.mediaText) || '';
          if (/prefers-reduced-motion/.test(cond)) { mediaBlocks++; rulesInside += r.cssRules.length; }
          else walk(r.cssRules);
        } else if (r.type === CSSRule.SUPPORTS_RULE) walk(r.cssRules);
      }
    };
    walk(rs);
  }
  const animated = [...document.querySelectorAll('body *')].filter(el => {
    const s = getComputedStyle(el);
    return (s.animationName && s.animationName !== 'none') ||
           (s.transitionDuration && s.transitionDuration.split(',').some(d => parseFloat(d) > 0));
  }).length;
  return {
    honours: mediaBlocks > 0,
    mediaBlocks, rulesInside,
    readableSheets: readable, corsBlockedSheets: blocked,
    animatedElements: animated,
    verdict: mediaBlocks > 0 ? 'правило есть'
      : (animated > 0 ? 'АНИМАЦИЯ ЕСТЬ, а правила prefers-reduced-motion НЕТ' : 'анимации нет, правило не требуется')
  };
})()
```

Если `corsBlockedSheets` больше нуля, часть стилей с другого домена прочитать нельзя —
вывод неполный, сказать об этом прямо.

---

## Проба 13 — Увеличение текста вдвое

Имитация системной настройки крупного шрифта. Ломается обычно то, что свёрстано
фиксированными высотами.

```js
(() => {
  const d = document.documentElement;
  const base = parseFloat(getComputedStyle(d).fontSize);
  const orig = d.style.fontSize;
  const beforeScroll = d.scrollWidth, vw = d.clientWidth;
  d.style.fontSize = (base * 2) + 'px';
  void d.offsetHeight;
  const afterScroll = d.scrollWidth;
  const clipped = [...document.querySelectorAll('body *')].filter(el => {
    if (el.children.length) return false;
    if (!(el.innerText || '').trim()) return false;
    const s = getComputedStyle(el);
    if (s.overflow === 'visible' && s.overflowY === 'visible') return false;
    return el.scrollHeight > el.clientHeight + 2 || el.scrollWidth > el.clientWidth + 2;
  }).slice(0, 15).map(el => ({
    text: (el.innerText || '').trim().slice(0, 35),
    sel: el.tagName.toLowerCase() + (el.className ? '.' + el.className.toString().trim().split(/\s+/)[0] : '')
  }));
  d.style.fontSize = orig;
  void d.offsetHeight;
  return {
    baseFontPx: base,
    scaledTo: base * 2,
    beforeScrollWidth: beforeScroll,
    afterScrollWidth: afterScroll,
    viewport: vw,
    newHorizontalScroll: afterScroll > vw && beforeScroll <= vw,
    clippedCount: clipped.length,
    clipped,
    note: afterScroll === beforeScroll ? 'Ширина не изменилась — возможно, размеры заданы в px и на настройку шрифта не реагируют, это тоже дефект доступности' : null
  };
})()
```

Отдельная находка — когда ничего не поменялось: значит текст свёрстан в `px` и системную
настройку крупного шрифта игнорирует.

---

## Проверка 404

Скриптом не делается — нужен переход:

```
navigate {url: "<origin>/__qa_probe_404__"}
```

Затем `get_page_text`. Правильно: осмысленная страница с понятным текстом и ссылкой
на главную. Неправильно: пустой экран, сырая ошибка сервера, молчаливый редирект
на главную (пользователь не понимает, что ссылка битая), страница с кодом 200.
