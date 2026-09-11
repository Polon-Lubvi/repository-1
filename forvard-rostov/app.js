/* =====================================================================
   РЕНДЕР И ИНТЕРАКТИВ. Растёт по мере согласования блоков.
   Тексты — в content.js, параметры — в config.js.
   ===================================================================== */
(function () {
  'use strict';

  var S = window.SITE;
  var C = window.CFG;
  var ic = window.icon;
  var PREFERS_STILL = window.matchMedia('(prefers-reduced-motion: reduce)');

  /* ---------- утилиты ---------- */
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function fmt(n) { return Math.round(n).toLocaleString('ru-RU'); }

  /* Ссылки в мессенджеры. Без номера в конфиге — «мёртвая» ссылка,
     чтобы это было заметно, а не вело в никуда. */
  function waLink(text) {
    if (!C.contacts.phone) return '#';
    var t = text || C.contacts.waText;
    return 'https://wa.me/' + C.contacts.phone + (t ? '?text=' + encodeURIComponent(t) : '');
  }
  function tgLink() { return C.contacts.telegram ? 'https://t.me/' + C.contacts.telegram : '#'; }
  function maxLink() { return C.contacts.max || '#'; }
  function deadAttr(href) { return href === '#' ? ' data-no-phone aria-disabled="true"' : ' target="_blank" rel="noopener"'; }

  /* {фигурные скобки} -> ярко-белым, остальной текст приглушённый.
     Так сделаны заголовки подблоков (блок 3). */
  function accent(text) {
    return esc(text).replace(/\{([^}]+)\}/g, '<span class="text-accent">$1</span>');
  }

  function lede(text) {
    return term(esc(text)
      .replace(/\{([^}]+)\}/g, '<b>$1</b>')
      .replace(/\n/g, '<br>'));         /* перенос строки внутри абзаца */
  }

  /* [[ТНВД|расшифровка]] -> термин с всплывающей подсказкой.
     На компьютере открывается наведением, на телефоне — тапом (wireTerms).
     Без модальных окон и библиотек — ТЗ §3.3. */
  function term(html) {
    return html.replace(/\[\[([^|\]]+)\|([^\]]+)\]\]/g, function (_, word, tip) {
      return '<button class="term" type="button" aria-expanded="false">' +
        word + '<span class="term__tip" role="tooltip">' + tip + '</span></button>';
    });
  }

  /* Реальное фото машины или размеченная заглушка (ТЗ §3.1) */
  function photo(state, eager) {
    if (state.photo) {
      return '<img src="' + esc(state.photo) + '" alt="' + esc(state.photoNeed) + '"' +
             (state.w && state.h ? ' width="' + state.w + '" height="' + state.h + '"' : '') +
             (eager ? '' : ' loading="lazy"') + '>';
    }
    return '<div class="photo-stub">' +
             '<span class="photo-stub__tag">' + esc(state.photoKind || 'Фото') + '</span>' +
             '<p class="photo-stub__text">' + esc(state.photoNeed) + '</p>' +
           '</div>';
  }

  /* Фото в скруглённых плашках справа от текста (блок 3).
     Одно фото — одна плашка, два — рядом. cap рисует подпись под кадром. */
  function shotsHtml(items) {
    if (!items || !items.length) return '';
    return '<div class="shots shots--' + items.length + '">' + items.map(function (x) {
      return '<figure class="shot">' +
        '<span class="shot__frame">' +
          (x.src
            ? '<img src="' + esc(x.src) + '" alt="' + esc(x.alt || x.need || '') + '"' +
              (x.w && x.h ? ' width="' + x.w + '" height="' + x.h + '"' : '') + ' loading="lazy">'
            : '<div class="photo-stub"><span class="photo-stub__tag">Фото</span>' +
              '<p class="photo-stub__text">' + esc(x.need || '') + '</p></div>') +
        '</span>' +
        (x.cap ? '<figcaption class="shot__cap">' + esc(x.cap) + '</figcaption>' : '') +
      '</figure>';
    }).join('') + '</div>';
  }

  /* Лента фото: листается влево-вправо (свайп на телефоне, стрелки на
     десктопе). Кадры одного размера — object-fit: cover в CSS их подрежет.
     variant задаёт пропорции плитки (см. .strip--* в blocks.css). */
  function photoStrip(photos, variant) {
    if (!photos || !photos.length) return '';
    var slides = photos.map(function (ph) {
      return '<figure class="strip__item">' +
        (ph.src
          ? '<img src="' + esc(ph.src) + '" alt="' + esc(ph.need || '') + '" loading="lazy">'
          : '<div class="photo-stub"><span class="photo-stub__tag">Фото</span>' +
              '<p class="photo-stub__text">' + esc(ph.need || '') + '</p></div>') +
      '</figure>';
    }).join('');
    return '<div class="strip strip--' + esc(variant) + '" data-strip>' +
      '<button class="strip__nav strip__nav--prev" type="button" aria-label="Предыдущее фото" hidden>' +
        ic('chevronL', { size: 20 }) + '</button>' +
      '<div class="strip__track">' + slides + '</div>' +
      '<button class="strip__nav strip__nav--next" type="button" aria-label="Следующее фото" hidden>' +
        ic('chevronR', { size: 20 }) + '</button>' +
    '</div>';
  }

  /* Счётчик установок: базовое + floor(прошло_суток × прирост) — ТЗ блок 1 */
  function installCount() {
    var c = C.counter;
    var since = new Date(c.since + 'T00:00:00');
    var days = Math.max(0, Math.floor((Date.now() - since.getTime()) / 86400000));
    return c.base + Math.floor(days * c.perDay);
  }

  /* Смена текста «роликом»: старая строка уезжает вверх, новая приходит снизу.
     Обе строки лежат в одной ячейке grid, поэтому вёрстка не дёргается. */
  function roll(box, html) {
    var cur = box.querySelector('.roll__line');
    if (!cur) { box.innerHTML = '<span class="roll__line">' + html + '</span>'; return; }
    if (cur.innerHTML === html || box.dataset.busy === '1') return;

    /* вкладка скрыта или анимации выключены — меняем сразу, без езды */
    if (document.hidden || PREFERS_STILL.matches) {
      box.innerHTML = '<span class="roll__line">' + html + '</span>';
      return;
    }

    box.dataset.busy = '1';

    var next = document.createElement('span');
    next.className = 'roll__line roll__line--enter';
    next.innerHTML = html;
    box.appendChild(next);

    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        cur.classList.add('roll__line--leave');
        next.classList.remove('roll__line--enter');
      });
    });

    /* Таймер — главный: даже если rAF не сработал, новая строка
       гарантированно останется видимой. */
    setTimeout(function () {
      cur.remove();
      next.classList.remove('roll__line--enter', 'roll__line--leave');
      box.dataset.busy = '0';
    }, 600);
  }

  /* Резервируем высоту под самый высокий из вариантов — тогда при смене
     строки блок не меняет размер и текст не «прыгает». */
  function reserveHeight(box, variants) {
    var probe = document.createElement('span');
    probe.className = 'roll__line';
    probe.style.cssText = 'position:absolute;left:0;top:0;width:100%;visibility:hidden;pointer-events:none';
    box.appendChild(probe);
    var max = 0;
    variants.forEach(function (html) { probe.innerHTML = html; max = Math.max(max, probe.offsetHeight); });
    probe.remove();
    box.style.minHeight = max + 'px';
  }

  /* Открыто ли сейчас — по графику из конфига, в часовом поясе сервиса */
  function isOpenNow() {
    var sc = C.schedule;
    if (!sc) return null;
    var d = new Date(new Date().toLocaleString('en-US', { timeZone: sc.tz }));
    if (sc.days.indexOf(d.getDay()) === -1) return false;
    var mins = d.getHours() * 60 + d.getMinutes();
    return mins >= sc.from && mins < sc.to;
  }

  /* =====================  ШАПКА  ===================== */
  function renderHeader() {
    var links = S.nav.map(function (l) {
      return '<li><a href="' + esc(l.href) + '">' + esc(l.label) + '</a></li>';
    }).join('');
    var mobileLinks = S.nav.map(function (l) {
      return '<a href="' + esc(l.href) + '" data-close-menu>' + esc(l.label) + '</a>';
    }).join('');

    var phone = C.contacts.phoneDisplay
      ? '<a class="header__phone" href="tel:+' + esc(C.contacts.phone) + '">' +
          ic('phone', { size: 15 }) + esc(C.contacts.phoneDisplay) + '</a>'
      : '';

    var logoMark = S.brand.logo
      ? '<img class="logo__mark logo__mark--img" src="' + esc(S.brand.logo) + '" alt="' + esc(S.brand.name) + '">'
      : '<span class="logo__mark">' + esc(S.brand.short) + '</span>';

    return '' +
    '<header class="header" id="site-header">' +
      '<div class="wrap header__inner">' +
        '<a class="logo" href="#top">' +
          logoMark +
          '<span class="logo__name">' +
            '<span class="logo__title">' + esc(S.brand.name) + '</span>' +
            '<span class="logo__sub">' + esc(S.brand.tagline) + '</span>' +
          '</span>' +
        '</a>' +
        '<nav class="nav"><ul style="display:flex;gap:24px">' + links + '</ul></nav>' +
        '<div class="header__side">' +
          '<span class="header__hours" id="work-status"><span class="header__dot"></span>' + esc(S.hours) + '</span>' +
          phone +
          '<a class="btn btn--soft btn--sm header__cta" href="' + waLink() + '"' + deadAttr(waLink()) + '>' + esc(S.headerCta) + '</a>' +
          '<button class="burger" id="burger" aria-label="Меню" aria-expanded="false">' + ic('menu', { size: 20 }) + '</button>' +
        '</div>' +
      '</div>' +
      '<div class="mobile-menu" id="mobile-menu">' +
        mobileLinks +
        '<a class="btn btn--cta mobile-menu__cta" href="' + waLink() + '"' + deadAttr(waLink()) + '>' + esc(S.hero.cta) + '</a>' +
      '</div>' +
    '</header>';
  }

  /* =====================  БЛОК 1 — Первый экран  ===================== */
  function renderHero() {
    var h = S.hero;

    var hooks = h.hooks.map(function (x) {
      return '<li class="hero__hook">' + ic(x.icon, { size: 18 }) +
        '<p><b>' + esc(x.title) + '</b> <span>' + esc(x.text) + '</span></p></li>';
    }).join('');

    var slides = h.states.map(function (st, i) {
      return '<div class="hero__slide' + (i === 0 ? ' is-active' : '') +
        '" data-slide="' + esc(st.key) + '">' + photo(st, i === 0) + '</div>';
    }).join('');

    var wa = waLink();

    return '' +
    '<section class="hero" id="top">' +

      /* слой 1 — кирпичная стена гаража */
      '<div class="hero__scene" aria-hidden="true">' +
        '<div class="scene__wall"></div>' +
        '<div class="scene__shade"></div>' +
      '</div>' +

      /* слой 2 — контент, две симметричные колонки */
      '<div class="wrap hero__inner">' +

        '<div class="hero__head">' +
          '<h1 class="hero__title">' + accent(h.title) +
            (h.engines ? '<span class="hero__engines">' + esc(h.engines) + '</span>' : '') +
          '</h1>' +
        '</div>' +

        '<div class="hero__body">' +

        '<div class="hero__text">' +
          '<p class="hero__term roll" id="hero-term" aria-live="polite"></p>' +
          '<ul class="hero__hooks">' + hooks + '</ul>' +
          '<div class="hero__actions">' +
            '<a class="btn btn--cta" href="' + wa + '"' + deadAttr(wa) + '>' +
              esc(h.cta) + ic('arrow', { size: 18 }) + '</a>' +
            '<p class="hero__counter">' +
              '<b id="hero-counter">' + fmt(installCount()) + '</b>' +
              '<span>' + esc(h.counterLabel) + '</span>' +
            '</p>' +
          '</div>' +
        '</div>' +

        '<div class="hero__media">' +
          '<div class="roll" id="hero-caption" aria-live="polite"></div>' +
          '<figure class="hero__photo">' + slides + '</figure>' +
        '</div>' +

        '</div>' +

      '</div>' +
    '</section>';
  }

  /* =====================  БЛОК 2 — Бегущая строка  ===================== */
  function renderClients() {
    var c = S.clients;
    var row = c.names.map(function (n) {
      return '<span class="clients__item">' + esc(n) + '</span>';
    }).join('');
    /* Список повторяем, чтобы группа была заведомо шире экрана,
       и делаем две одинаковые группы — тогда лента идёт по кругу
       без разрыва и без пустого хвоста. */
    var group = '<div class="clients__group">' + row + row + row + '</div>';
    return '<section class="clients">' +
      '<div class="clients__strip">' +
        '<div class="clients__track" id="clients-track">' + group + group + '</div>' +
      '</div>' +
      '<p class="clients__note wrap">' + esc(c.note) + '</p>' +
    '</section>';
  }

  /* =====================  БЛОК 3 — Что мы делаем  ===================== */
  function panelHtml(i) {
    var b = S.tuning.subblocks[i];

    var groups = (b.blocks || []).map(function (g) {
      return '<div class="panel__group">' +
        (g.h ? '<span class="panel__h">' + esc(g.h) + '</span>' : '') +
        '<p class="panel__text">' + lede(g.text) + '</p>' +
      '</div>';
    }).join('');

    /* Две панели вместо сплошных абзацев: слева тип впрыска, справа второй,
       под каждой — счётчик машин. Читается взглядом, а не абзацами. */
    var cards = '';
    if (b.cards && b.cards.length) {
      cards = '<div class="panel__cards-wrap">' +
        (b.cardsLead ? '<span class="panel__cards-lead">' + esc(b.cardsLead) + '</span>' : '') +
        '<div class="panel__cards">' + b.cards.map(function (c) {
          return '<div class="panel__card">' +
            '<span class="panel__card-h">' + esc(c.h) + '</span>' +
            (c.sub ? '<span class="panel__card-sub">' + esc(c.sub) + '</span>' : '') +
            '<p class="panel__card-text">' + lede(c.text) + '</p>' +
            (c.note ? '<p class="panel__card-note">' + esc(c.note) + '</p>' : '') +
            (c.count ? '<span class="panel__count">' + esc(c.count) + '</span>' : '') +
          '</div>';
        }).join('') + '</div>' +
        (b.cardsOut ? '<p class="panel__cards-out">' + esc(b.cardsOut) + '</p>' : '') +
      '</div>';
    }

    var revUrl = (C.yandex && C.yandex.reviews) || '';
    var revTag = (b.review && b.review.link && revUrl) ? 'a' : 'div';
    var revAttr = revTag === 'a'
      ? ' href="' + revUrl + '" target="_blank" rel="noopener" title="Открыть отзыв на Яндекс.Картах"'
      : '';
    var review = b.review ? '<' + revTag + ' class="panel__review' + (revTag === 'a' ? ' is-link' : '') + '"' + revAttr + '>' +
        '<div class="review__stars">' + [0,1,2,3,4].map(function(){return ic('star',{size:14});}).join('') + '</div>' +
        '<p class="review__text">«' + esc(b.review.text) + '»</p>' +
        '<div class="review__who">' +
          '<span class="review__avatar">' + esc(b.review.name.charAt(0)) + '</span>' +
          '<span><b class="review__name">' + esc(b.review.name) + '</b>' +
          '<span class="review__meta">' + esc(b.review.meta) + '</span></span>' +
          (revTag === 'a' ? '<span class="review__go">' + ic('arrow', { size: 15 }) + '</span>' : '') +
        '</div>' +
      '</' + revTag + '>' : '';

    var ctas = b.ctas.map(function (x) {
      var href = waLink(x.topic);
      return '<a class="btn btn--cta" href="' + href + '"' + deadAttr(href) + '>' +
        esc(x.label) + ic('arrow', { size: 16 }) + '</a>';
    }).join('');

    /* Строка-вывод и сноска лежат отдельно от колонки — во всю ширину,
       чтобы влезали в одну строку и не жались в половину экрана. */
    /* Строка-вывод, сноска и кнопки идут во всю ширину под колонками:
       так они влезают в одну строку, а человек читает вывод и сноску
       прямо перед тем, как нажать кнопку. */
    var foot = '<div class="panel__foot">' +
        (b.accentLine ? '<p class="panel__accent">' + esc(b.accentLine) + '</p>' : '') +
        (b.note ? '<p class="panel__note">' + esc(b.note) + '</p>' : '') +
        '<div class="panel__ctas">' + ctas + '</div>' +
      '</div>';

    /* Подблок с панелями идёт в одну колонку во всю ширину: две панели
       рядом внутри половины экрана были бы слишком узкими для чтения. */
    var body = (groups || review || b.heading)
      ? '<div class="panel__body">' +
          (b.heading ? '<h3 class="panel__heading">' + esc(b.heading) + '</h3>' : '') +
          groups +
          review +
        '</div>'
      : '';

    var hasShots = !!(b.shots && b.shots.length);
    return '<div class="panel' + (cards ? ' panel--cards' : '') +
      (hasShots ? ' panel--shots' : '') + '" data-panel="' + esc(b.key) + '">' +
      body +
      cards +
      '<div class="panel__media">' +
        (b.shots && b.shots.length
          ? shotsHtml(b.shots)
          : '<figure class="panel__figure">' + photo(b, false) + '</figure>') +
      '</div>' +
      foot +
    '</div>';
  }

  function renderTuning() {
    var t = S.tuning;
    var tabs = t.subblocks.map(function (b, i) {
      return '<button class="tab' + (i === 0 ? ' is-active' : '') +
        '" data-tab="' + i + '" id="tuning-' + esc(b.key) + '">' + esc(b.tab) + '</button>';
    }).join('');

    return '<section class="tuning" id="tuning"><div class="wrap">' +
      '<h2 class="tuning__title">' + accent(t.title) + '</h2>' +
      '<div class="tabs" role="tablist">' + tabs + '</div>' +
      '<div class="tuning__stage">' +
        '<button class="tuning__arrow tuning__arrow--prev" id="tuning-prev" aria-label="Предыдущий">' + ic('chevronL', { size: 30 }) + '</button>' +
        '<div id="tuning-panel">' + panelHtml(0) + '</div>' +
        '<button class="tuning__arrow tuning__arrow--next" id="tuning-next" aria-label="Следующий">' + ic('chevronR', { size: 30 }) + '</button>' +
      '</div>' +
    '</div></section>';
  }

  /* =====================  БЛОК 4 — Сравнение подходов  ===================== */
  function renderCompare() {
    var c = S.compare;

    var rows = c.rows.map(function (r) {
      return '<div class="compare__row">' +
        '<span class="compare__them" data-label="' + esc(c.headThem) + '">' + ic('cross', { size: 15 }) + '<span>' + esc(r.them) + '</span></span>' +
        '<span class="compare__us" data-label="' + esc(c.headUs) + '">' + ic('check', { size: 15 }) + '<span>' + lede(r.us) + '</span></span>' +
      '</div>';
    }).join('');

    var photos = c.photos.map(function (ph) {
      return '<figure class="compare__figure">' +
        photo({ photo: ph.src || null, photoKind: ph.kind, photoNeed: ph.need, w: ph.w, h: ph.h }, false) +
      '</figure>';
    }).join('');

    return '<section class="compare" id="compare"><div class="wrap">' +
      '<h2 class="compare__title">' + accent(c.title) + '</h2>' +
      '<div class="compare__grid">' +
        '<div class="compare__table">' +
          '<div class="compare__head"><span>' + esc(c.headThem) + '</span><span>' + esc(c.headUs) + '</span></div>' +
          rows +
          '<p class="compare__closing">' + esc(c.closing) + '</p>' +
        '</div>' +
        '<div class="compare__photos">' + photos + '</div>' +
      '</div>' +

      /* раскрывающиеся пункты: что входит в ТО, как считаем цену, свои запчасти */
      '<div class="acc">' + accordion(c.accordion) + '</div>' +

      /* гарантия */
      warrantyHtml() +
    '</div></section>';
  }

  /* Раскрывающиеся пункты. Работают «на месте», без модальных окон. */
  function accordion(items) {
    return (items || []).map(function (a, i) {
      var body = a.items
        ? '<ul class="acc__list">' + a.items.map(function (it) {
            return '<li>' + ic('check', { size: 15 }) + '<span><b>' + esc(it.b) + '</b>' +
              (it.t ? ' — ' + esc(it.t) : '') + '</span></li>';
          }).join('') + '</ul>'
        : '<p class="acc__text">' + esc(a.text) + '</p>';
      return '<div class="acc__item" data-acc="' + i + '">' +
        '<button class="acc__head" aria-expanded="false">' + esc(a.title) + ic('chevronDown', { size: 18 }) + '</button>' +
        '<div class="acc__panel"><div class="acc__inner">' + body +
          (a.closing ? '<p class="acc__closing">' + esc(a.closing) + '</p>' : '') +
        '</div></div>' +
      '</div>';
    }).join('');
  }

  /* Гарантия — идёт следом за раскрывающимися пунктами */
  function warrantyHtml() {
    var w = S.warranty;
    var cards = w.cards.map(function (x) {
      return '<div class="warranty__card' + (x.good ? ' is-good' : '') + '">' +
        '<span class="warranty__type">' + esc(x.type) + '</span>' +
        '<span class="warranty__km">' + esc(x.km) + '</span>' +
        '<span class="warranty__or">' + esc(x.or) + '</span>' +
      '</div>';
    }).join('');
    return '<div class="warranty">' +
      '<h3 class="warranty__title">' + esc(w.title) + '</h3>' +
      '<div class="warranty__cards">' + cards + '</div>' +
      (w.note ? '<p class="warranty__note">' + esc(w.note) + '</p>' : '') +
    '</div>';
  }

  /* =====================  БЛОК 5 — Мастера  ===================== */
  function renderTeam() {
    var t = S.team;

    /* Пустая карточка показывает, что именно сюда встанет: должность,
       имя, стаж и цитата — чтобы заказчику было понятно, что прислать. */
    function slot(value, label) {
      return value
        ? esc(value)
        : '<i class="person__slot">' + esc(label) + '</i>';
    }

    var people = t.people.map(function (p) {
      var empty = !p.name;
      return '<article class="person' + (empty ? ' person--empty' : '') + '">' +
        '<figure class="person__figure">' +
          photo({ photo: p.photo, photoKind: 'Фото', photoNeed: p.photoNeed }, false) +
        '</figure>' +
        '<div>' +
          '<span class="person__role">' + slot(p.role, 'Специфика работы') + '</span>' +
          '<b class="person__name">' + slot(p.name, 'Имя') + '</b>' +
          '<span class="person__years">' + slot(p.years, 'Стаж') + '</span>' +
          '<p class="person__quote">' + slot(p.quote, 'Цитата') + '</p>' +
        '</div>' +
      '</article>';
    }).join('');

    var not = t.not.map(function (x) {
      var tail = x.href
        ? '<a href="' + esc(x.href) + '">' + esc(x.t) + '</a>'
        : esc(x.t);
      return '<li class="not__item">' + ic('cross', { size: 15 }) +
        '<span><b>' + esc(x.b) + '</b> — ' + tail + '</span></li>';
    }).join('');

    return '<section class="team" id="team"><div class="wrap">' +
      '<h2 class="team__title">' + accent(t.title) + '</h2>' +
      '<div class="team__grid">' + people + '</div>' +
      '<div class="not">' +
        '<h3 class="not__title">' + esc(t.notTitle) + '</h3>' +
        '<ul class="not__list">' + not + '</ul>' +
      '</div>' +
    '</div></section>';
  }

  /* =====================  БЛОК 7 — Отзывы  ===================== */
  function renderReviews() {
    var r = S.reviews;
    var url = (C.yandex && C.yandex.reviews) || '';
    var org = (C.yandex && C.yandex.org) || url;
    var avitoUrl = (C.links && (C.links.avitoReviews || C.links.avito)) || '';
    var stars = [0,1,2,3,4].map(function () { return ic('star', { size: 14 }); }).join('');

    function ratingCard(data, link) {
      return '<a class="rating" href="' + esc(link) + '"' + (link ? ' target="_blank" rel="noopener"' : '') + '>' +
        '<span class="rating__value">' + esc(data.value) + '</span>' +
        '<span>' +
          '<span class="rating__stars">' + stars + '</span>' +
          '<span class="rating__counts">' + esc(data.counts) + '</span>' +
          '<span class="rating__src">' + esc(data.source) + '</span>' +
        '</span>' +
        '<span class="rating__go">' + ic('arrow', { size: 18 }) + '</span>' +
      '</a>';
    }

    var ratings = '<div class="reviews__ratings">' +
      ratingCard(r.rating, org) +
      (r.ratingAvito && avitoUrl ? ratingCard(r.ratingAvito, avitoUrl) : '') +
    '</div>';

    var items = r.items.map(function (x) {
      var isAv = x.src === 'Авито';
      var href = isAv ? avitoUrl : url;
      var srcLabel = x.src || r.rating.source;
      return '<a class="review" href="' + esc(href) + '"' + (href ? ' target="_blank" rel="noopener"' : '') +
        ' title="Открыть отзыв на ' + esc(srcLabel) + '">' +
        '<span class="review__top">' +
          '<span class="review__ava">' + esc(x.name.charAt(0)) + '</span>' +
          '<span class="review__who"><b>' + esc(x.name) + '</b>' +
            (x.meta ? '<span>' + esc(x.meta) + '</span>' : '') + '</span>' +
        '</span>' +
        '<span class="rating__stars">' + stars + '</span>' +
        '<span class="review__body">' + esc(x.text) + '</span>' +
        '<span class="review__foot">' + ic('star', { size: 13 }) + esc(srcLabel) + '</span>' +
      '</a>';
    }).join('');

    var buttons = r.cta.buttons.map(function (b) {
      var href = waLink(b.topic);
      return '<a class="btn btn--cta" href="' + href + '"' + deadAttr(href) + '>' +
        esc(b.label) + ic('arrow', { size: 16 }) + '</a>';
    }).join('');

    return '<section class="reviews" id="reviews"><div class="wrap">' +
      '<div class="reviews__head">' +
        '<h2 class="reviews__lead">' + esc(r.lead) + '</h2>' +
        ratings +
      '</div>' +
      '<div class="reviews__grid">' + items + '</div>' +
      '<div class="reviews__cta">' +
        '<p>' + esc(r.cta.lead) + '</p>' +
        '<div class="reviews__buttons">' + buttons + '</div>' +
      '</div>' +
    '</div></section>';
  }

  /* =====================  БЛОК 8 — Частые вопросы  ===================== */
  function renderFaq() {
    var f = S.faq;

    var items = f.items.map(function (it, i) {
      var photos = photoStrip(it.photos, 'faq');
      return '<div class="acc__item" data-acc="faq-' + i + '">' +
        '<button class="acc__head" type="button" aria-expanded="false">' +
          '<span>' + esc(it.q) + '</span>' + ic('chevronDown', { size: 20 }) +
        '</button>' +
        '<div class="acc__panel"><div class="acc__inner">' +
          '<p class="acc__text">' + esc(it.a) + '</p>' +
          photos +
        '</div></div>' +
      '</div>';
    }).join('');

    return '<section class="faq" id="faq"><div class="wrap">' +
      '<h2 class="faq__lead">' + esc(f.lead) + '</h2>' +
      '<div class="acc faq__acc">' + items + '</div>' +
    '</div></section>';
  }

  /* =====================  БЛОК 9 — Как доехать  ===================== */
  function renderLocation() {
    var l = S.location;
    var y = C.yandex || {};

    var routes = l.routes.map(function (r) {
      return '<div class="loc__route"><span>' + esc(r.from) + '</span><span>' +
        (r.time ? esc(r.time) : '') + '</span></div>';
    }).join('');

    return '<section class="loc" id="contacts"><div class="wrap">' +
      '<h2 class="loc__lead">' + esc(l.lead) + '</h2>' +
      '<div class="loc__grid">' +

        '<div>' +
          '<a class="loc__map" href="' + esc(y.org || '#') + '" target="_blank" rel="noopener" ' +
            'aria-label="Открыть в Яндекс.Картах">' +
            '<img class="loc__map-img" src="' + esc(l.mapImage) + '" ' +
              'alt="Карта: ' + esc(l.address) + '" loading="lazy" width="1200" height="825">' +
          '</a>' +
        '</div>' +

        '<div class="loc__info">' +
          '<p class="loc__addr">' + esc(l.address) + '</p>' +
          '<p class="loc__note">' + esc(l.note) + '</p>' +
          '<div class="loc__block">' +
            '<b>' + esc(l.hoursLabel) + '</b>' +
            '<p class="loc__hours">' + esc(l.hours) + '</p>' +
          '</div>' +
          '<div class="loc__block">' +
            '<b>' + esc(l.routesLabel) + '</b>' +
            '<div class="loc__routes">' + routes + '</div>' +
          '</div>' +
          (y.org ? '<a class="btn btn--map" href="' + esc(y.org) + '" target="_blank" rel="noopener">' +
            'Открыть в Яндекс.Картах' + ic('arrow', { size: 16 }) + '</a>' : '') +
        '</div>' +

      '</div>' +

      /* фото гаража — во всю ширину блока, все сразу видно, листать не нужно */
      '<div class="loc__gallery">' + l.photos.map(function (ph) {
        return '<figure class="loc__shot">' +
          (ph.src
            ? '<img src="' + esc(ph.src) + '" alt="' + esc(ph.need || '') + '" loading="lazy">'
            : '<div class="photo-stub"><span class="photo-stub__tag">Фото</span>' +
              '<p class="photo-stub__text">' + esc(ph.need || '') + '</p></div>') +
        '</figure>';
      }).join('') + '</div>' +
    '</div></section>';
  }

  /* =====================  БЛОК 10 — Форма записи  ===================== */
  function renderForm() {
    var f = S.form;
    var wa = waLink(f.submitTopic);

    return '<section class="form" id="zapis"><div class="wrap">' +
      '<div class="form__card">' +
        '<h2 class="form__lead">' + esc(f.lead) + '</h2>' +
        '<a class="btn btn--cta form__submit" href="' + wa + '"' + deadAttr(wa) + '>' +
          esc(f.submit) + ic('arrow', { size: 17 }) + '</a>' +
        '<p class="form__note">' + lede(f.note) + '</p>' +
      '</div>' +
    '</div></section>';
  }

  /* =====================  БЛОК 11 — Подвал  ===================== */
  function renderFooter() {
    var f = S.footer;
    var y = C.yandex || {}, links = C.links || {}, legal = C.legal || {};
    var ph = C.contacts.phoneDisplay;

    var net = '';
    if (y.org)       net += '<a href="' + esc(y.org) + '" target="_blank" rel="noopener">Яндекс.Карты</a>';
    if (links.avito) net += '<a href="' + esc(links.avito) + '" target="_blank" rel="noopener">Авито</a>';

    var reqs = [];
    if (legal.ogrnip) reqs.push('ОГРНИП ' + esc(legal.ogrnip));
    if (legal.inn)    reqs.push('ИНН ' + esc(legal.inn));
    if (legal.okpo)   reqs.push('ОКПО ' + esc(legal.okpo));

    return '<footer class="footer"><div class="wrap">' +
      '<div class="footer__grid">' +

        '<div>' +
          '<div class="footer__brand">' +
            (S.brand.logo
              ? '<img class="logo__mark logo__mark--img" src="' + esc(S.brand.logo) + '" alt="' + esc(S.brand.name) + '">'
              : '<span class="logo__mark">' + esc(S.brand.short) + '</span>') +
            '<b>' + esc(legal.orgName || S.brand.name) + '</b>' +
          '</div>' +
          '<p class="footer__addr">' + esc(f.address) + '<br>' + esc(f.hours) + '</p>' +
          '<p class="footer__disc">' + esc(f.disclaimer) + '</p>' +
        '</div>' +

        '<div class="footer__col">' +
          '<b>Контакты</b>' +
          (ph ? '<a href="tel:+' + esc(C.contacts.phone) + '">' + esc(ph) + '</a>' : '<span>Телефон — уточняется</span>') +
          '<a href="' + waLink() + '"' + deadAttr(waLink()) + '>Написать в WhatsApp</a>' +
        '</div>' +

        '<div class="footer__col">' +
          '<b>' + esc(f.linksTitle) + '</b>' +
          (net || '<span>Ссылки — уточняются</span>') +
        '</div>' +

      '</div>' +

      '<div class="footer__bottom">' +
        '<span>© ' + new Date().getFullYear() + ' ' + esc(legal.orgName || S.brand.name) +
          (reqs.length ? ' · ' + reqs.join(' · ') : '') + ' · Карта © OpenStreetMap</span>' +
        '<a href="#">' + esc(f.privacyLabel) + '</a>' +
      '</div>' +
    '</div></footer>';
  }

  /* =====================  ПЛАВАЮЩАЯ КНОПКА WA (моб.)  ===================== */
  function renderWaFloat() {
    var wa = waLink();
    return '<a class="wa-float" href="' + wa + '"' + deadAttr(wa) + ' aria-label="Написать в WhatsApp">' +
      ic('whatsapp', { size: 26 }) + '</a>';
  }

  /* =====================  СБОРКА  ===================== */
  function build() {
    document.title = S.meta.title;
    var d = document.querySelector('meta[name="description"]');
    if (d) d.setAttribute('content', S.meta.description);

    document.getElementById('app').innerHTML =
      renderHeader() +
      '<main>' + renderHero() + renderClients() + renderTuning() + renderCompare() + renderTeam() + renderReviews() + renderFaq() + renderLocation() + renderForm() + '</main>' +
      renderFooter() +
      renderWaFloat();

    if (!C.contacts.phone) {
      console.warn('[config] Не задан contacts.phone — кнопки мессенджеров пока не ведут никуда.');
    }

    wireHeader();
    wireHero();
    wireClients();
    wireTuning();
    wireAccordions();
    wireCarousels();
    wireTerms();
  }

  /* ---------- шапка ---------- */
  function wireHeader() {
    var header = document.getElementById('site-header');
    var onScroll = function () { header.classList.toggle('is-scrolled', window.scrollY > 12); };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });

    var burger = document.getElementById('burger');
    var menu = document.getElementById('mobile-menu');
    var setOpen = function (open) {
      menu.classList.toggle('is-open', open);
      burger.setAttribute('aria-expanded', open ? 'true' : 'false');
      burger.innerHTML = ic(open ? 'close' : 'menu', { size: 20 });
    };
    burger.addEventListener('click', function () { setOpen(!menu.classList.contains('is-open')); });
    menu.addEventListener('click', function (e) { if (e.target.closest('[data-close-menu]')) setOpen(false); });

    /* зелёный когда открыто, красный когда закрыто */
    var status = document.getElementById('work-status');
    var refresh = function () {
      var open = isOpenNow();
      if (open === null) return;
      status.classList.toggle('is-open', open);
      status.title = open ? 'Сейчас открыто' : 'Сейчас закрыто';
    };
    refresh();
    setInterval(refresh, 60000);
  }

  /* ---------- блок 1: переключение состояний ---------- */
  function wireHero() {
    var states = S.hero.states;
    var termBox = document.getElementById('hero-term');
    var capBox = document.getElementById('hero-caption');
    var slides = [].slice.call(document.querySelectorAll('.hero__slide'));

    var reduced = PREFERS_STILL.matches;
    var idx = 0;
    var timer = null;
    var paused = false;   // пауза от ?car= — до первого действия пользователя

    function termHtml(st) {
      var t = esc(st.term);
      return st.termHref ? '<a href="' + esc(st.termHref) + '">' + t + '</a>' : t;
    }
    function capHtml(st) {
      return '<span class="hero__caption-title">' + esc(st.caption) + '</span>' +
             '<span class="hero__caption-sub">' + esc(st.sub) + '</span>';
    }

    function paint(i) {
      var st = states[i];
      slides.forEach(function (el, k) { el.classList.toggle('is-active', k === i); });
      roll(termBox, termHtml(st));
      roll(capBox, capHtml(st));
    }

    function schedule() {
      clearTimeout(timer);
      if (reduced || paused || document.hidden) return;
      var ms = C.hero.durations[states[idx].key] || 8000;
      timer = setTimeout(function () {
        idx = (idx + 1) % states.length;
        paint(idx);
        schedule();
      }, ms);
    }

    /* ?car=simple|china|commercial — открыть на состоянии и встать на паузу */
    var carParam = new URLSearchParams(location.search).get('car');
    if (carParam) {
      var found = states.findIndex(function (s) { return s.key === carParam; });
      if (found > -1) {
        idx = found;
        paused = true;
        var evs = ['scroll', 'pointerdown', 'keydown'];
        var resume = function () {
          paused = false;
          schedule();
          evs.forEach(function (ev) { window.removeEventListener(ev, resume); });
        };
        evs.forEach(function (ev) { window.addEventListener(ev, resume, { once: true, passive: true }); });
      }
    }

    /* высота под самый длинный вариант — чтобы блок не дёргался при смене */
    var fit = function () {
      reserveHeight(termBox, states.map(termHtml));
      reserveHeight(capBox, states.map(capHtml));
    };
    fit();
    var rt;
    window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(fit, 180); });

    document.addEventListener('visibilitychange', function () {
      if (document.hidden) clearTimeout(timer); else schedule();
    });

    paint(idx);
    schedule();
  }

  /* ---------- блок 2: лента стоит, пока её не видно ---------- */
  function wireClients() {
    var track = document.getElementById('clients-track');
    if (!track || !('IntersectionObserver' in window)) return;
    new IntersectionObserver(function (entries) {
      track.classList.toggle('is-paused', !entries[0].isIntersecting);
    }).observe(track);
  }

  /* ---------- блок 3: три подблока ---------- */
  function wireTuning() {
    var subs = S.tuning.subblocks;
    var panel = document.getElementById('tuning-panel');
    var tabs = [].slice.call(document.querySelectorAll('.tab'));
    var section = document.getElementById('tuning');
    var idx = 0;

    /* Автосмены нет: подблоки переключаются только вкладками и стрелками.
       То, что подблоков несколько, видно по вкладкам — сам текст не двигается. */
    function show(i) {
      idx = (i + subs.length) % subs.length;
      panel.innerHTML = panelHtml(idx);
      tabs.forEach(function (t, k) { t.classList.toggle('is-active', k === idx); });
    }

    function byUser(i) { show(i); }

    tabs.forEach(function (t, i) { t.addEventListener('click', function () { byUser(i); }); });
    document.getElementById('tuning-prev').addEventListener('click', function () { byUser(idx - 1); });
    document.getElementById('tuning-next').addEventListener('click', function () { byUser(idx + 1); });

    /* ссылка «От 72 часов — и вот почему» ведёт сразу на нужный подблок */
    function fromHash() {
      var m = /^#tuning-(.+)$/.exec(location.hash);
      if (!m) return;
      var i = subs.findIndex(function (b) { return b.key === m[1]; });
      if (i > -1) { byUser(i); section.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    }
    window.addEventListener('hashchange', fromHash);
    fromHash();
  }

  /* ---------- блок 5: калькулятор и раскрывающиеся пункты ---------- */
  /* ---------- раскрывающиеся пункты: блок 4 и вопросы (блок 8) ----------
     Работают «на месте», без модальных окон. Панель едет по max-height,
     конкретную высоту ставим из scrollHeight — с фото внутри тоже корректно. */
  function wireAccordions() {
    document.querySelectorAll('.acc__item').forEach(function (item) {
      var head = item.querySelector('.acc__head');
      var panel = item.querySelector('.acc__panel');
      head.addEventListener('click', function () {
        var open = item.classList.toggle('is-open');
        head.setAttribute('aria-expanded', open ? 'true' : 'false');
        panel.style.maxHeight = open ? (panel.scrollHeight + 'px') : '';
      });
      /* если внутри появятся настоящие фото — пересчитать высоту после загрузки */
      panel.querySelectorAll('img').forEach(function (img) {
        img.addEventListener('load', function () {
          if (item.classList.contains('is-open')) panel.style.maxHeight = panel.scrollHeight + 'px';
        });
      });
    });
  }

  /* ---------- блок 9: карта грузится по клику ---------- */
  /* Термины с подсказкой. Слушаем на документе, а не на самих словах:
     панель блока 3 перерисовывается при смене вкладки, и обычные
     обработчики бы отваливались. На компьютере подсказка и так открыта
     по наведению — здесь только тап и закрытие. */
  function wireTerms() {
    /* Подсказка выравнена по левому краю слова. Если слово стоит у правого
       края экрана, плашка вылезала бы за него — сдвигаем ровно настолько,
       чтобы она целиком помещалась. Меряем до показа: она hidden, но
       размеры у неё уже есть. */
    function placeTip(t) {
      var tip = t.querySelector('.term__tip');
      if (!tip) return;
      tip.style.left = '';
      var r = tip.getBoundingClientRect();
      var vw = document.documentElement.clientWidth;
      var over = r.right - (vw - 12);
      if (over > 0) tip.style.left = -Math.ceil(over) + 'px';
      else if (r.left < 12) tip.style.left = Math.ceil(12 - r.left) + 'px';
    }
    ['mouseover', 'focusin'].forEach(function (ev) {
      document.addEventListener(ev, function (e) {
        var t = e.target.closest ? e.target.closest('.term') : null;
        if (t) placeTip(t);
      }, { passive: true });
    });
    window.addEventListener('resize', function () {
      document.querySelectorAll('.term__tip').forEach(function (tip) { tip.style.left = ''; });
    });

    function closeOpen(except) {
      var open = document.querySelector('.term.is-open');
      if (open && open !== except) {
        open.classList.remove('is-open');
        open.setAttribute('aria-expanded', 'false');
      }
    }
    document.addEventListener('click', function (e) {
      var t = e.target.closest ? e.target.closest('.term') : null;
      closeOpen(t);
      if (!t) return;
      e.preventDefault();
      placeTip(t);
      var open = t.classList.toggle('is-open');
      t.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeOpen(null);
    });
  }

  /* Ленты фото (блок 9 и блок 8): стрелки листают на одну плитку,
     прячутся у краёв и когда листать нечего. Свайп работает и без JS. */
  function wireCarousels() {
    document.querySelectorAll('[data-strip]').forEach(function (strip) {
      var track = strip.querySelector('.strip__track');
      var prev = strip.querySelector('.strip__nav--prev');
      var next = strip.querySelector('.strip__nav--next');
      if (!track || !prev || !next) return;

      function step() {
        var item = track.querySelector('.strip__item');
        return item ? item.getBoundingClientRect().width + 10 : track.clientWidth * 0.8;
      }
      function sync() {
        var max = track.scrollWidth - track.clientWidth - 1;
        var scrollable = max > 4;
        prev.hidden = !scrollable || track.scrollLeft <= 2;
        next.hidden = !scrollable || track.scrollLeft >= max;
      }
      prev.addEventListener('click', function () { track.scrollBy({ left: -step(), behavior: 'smooth' }); });
      next.addEventListener('click', function () { track.scrollBy({ left:  step(), behavior: 'smooth' }); });
      track.addEventListener('scroll', sync, { passive: true });
      window.addEventListener('resize', sync);
      /* картинки грузятся лениво — пересчитать, когда размеры станут известны */
      track.querySelectorAll('img').forEach(function (img) { img.addEventListener('load', sync); });
      sync();
    });
  }

  /* ---------- запуск ---------- */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', build);
  } else { build(); }
})();
