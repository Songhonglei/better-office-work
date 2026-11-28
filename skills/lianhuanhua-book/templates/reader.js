(function () {
  var root = document.documentElement;
  root.classList.add("js");

  var spreads = Array.prototype.slice.call(document.querySelectorAll(".spread"));
  if (!spreads.length) return;

  var total = spreads.length;
  var CN = "零一二三四五六七八九十".split("");
  function cn(n) {
    if (n <= 10) return n === 10 ? "十" : CN[n];
    if (n < 20) return "十" + CN[n - 10];
    if (n < 100) {
      var t = Math.floor(n / 10), u = n % 10;
      return CN[t] + "十" + (u ? CN[u] : "");
    }
    return String(n);
  }
  function label(i) {
    return i === 0 ? "序" : cn(i);
  }

  var countEl = document.getElementById("count");
  var prevBtn = document.getElementById("prev");
  var nextBtn = document.getElementById("next");
  var fill = document.getElementById("fill");
  var track = document.getElementById("track");
  var modeBtn = document.getElementById("mode");

  var single = false;
  var cur = 0;
  var lock = false;
  var loaded = {};
  var userNavigated = false;

  function updateUI() {
    if (countEl) countEl.textContent = label(cur) + " / " + label(total - 1);
    if (prevBtn) prevBtn.disabled = cur === 0;
    if (nextBtn) nextBtn.disabled = cur === total - 1;
    if (fill) fill.style.width = (total === 1 ? 100 : (cur / (total - 1)) * 100) + "%";
  }

  function preload(i) {
    if (!single) return;
    [i + 1, i + 2, i - 1].forEach(function (k) {
      if (k < 0 || k >= total || loaded[k]) return;
      var img = spreads[k].querySelector("img");
      if (!img) return;
      loaded[k] = true;
      var p = new Image();
      p.src = img.getAttribute("src");
    });
  }

  function goTo(i, smooth) {
    userNavigated = true;
    i = Math.max(0, Math.min(total - 1, i));
    cur = i;
    if (single) {
      spreads.forEach(function (s, k) {
        s.classList.toggle("active", k === i);
      });
      window.scrollTo({ top: 0, behavior: "auto" });
    } else {
      var el = spreads[i];
      var y = el.getBoundingClientRect().top + window.pageYOffset - 62;
      lock = true;
      if (smooth === false) {
        // 临时关掉 CSS 的 scroll-behavior，避免瞬移变平滑滚动
        var html = document.documentElement;
        var prev = html.style.scrollBehavior;
        html.style.scrollBehavior = "auto";
        window.scrollTo(0, y);
        html.style.scrollBehavior = prev;
      } else {
        window.scrollTo({ top: y, behavior: "smooth" });
      }
      window.setTimeout(function () { lock = false; }, smooth === false ? 60 : 620);
    }
    updateUI();
    preload(i);
    if (history.replaceState) {
      try { history.replaceState(null, "", "#p" + i); } catch (e) {}
    }
  }

  function next() { if (cur < total - 1) goTo(cur + 1); }
  function prev() { if (cur > 0) goTo(cur - 1); }

  document.addEventListener("keydown", function (e) {
    var tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "button" || tag === "a" || e.target.isContentEditable) return;
    if (e.key === "ArrowRight" || e.key === "PageDown") { e.preventDefault(); next(); }
    else if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); prev(); }
    else if (e.key === " ") { e.preventDefault(); next(); }
    else if (e.key === "Home") { e.preventDefault(); goTo(0); }
    else if (e.key === "End") { e.preventDefault(); goTo(total - 1); }
  });

  // 单页模式下点击画面左右三分之一翻页
  spreads.forEach(function (sp) {
    var fig = sp.querySelector(".frame");
    if (!fig) return;
    fig.addEventListener("click", function (e) {
      if (!single) return;
      var r = fig.getBoundingClientRect();
      var x = e.clientX - r.left;
      if (x < r.width / 3) prev();
      else if (x > (r.width * 2) / 3) next();
    });
  });

  // 触摸滑动：单页模式翻页
  var sx = 0, sy = 0, moved = false;
  document.addEventListener("touchstart", function (e) {
    if (e.touches.length !== 1) return;
    sx = e.touches[0].clientX;
    sy = e.touches[0].clientY;
    moved = false;
  }, { passive: true });

  document.addEventListener("touchmove", function (e) {
    if (e.touches.length !== 1) return;
    var dx = e.touches[0].clientX - sx;
    var dy = e.touches[0].clientY - sy;
    if (Math.abs(dx) > 12 && Math.abs(dx) > Math.abs(dy)) moved = true;
  }, { passive: true });

  document.addEventListener("touchend", function (e) {
    if (!moved || !single) return;
    var dx = (e.changedTouches[0] || {}).clientX - sx;
    if (dx < -40) next();
    else if (dx > 40) prev();
  }, { passive: true });

  // 连续模式：滚动定位当前页
  var ticking = false;
  window.addEventListener("scroll", function () {
    if (single || lock || ticking) return;
    ticking = true;
    window.requestAnimationFrame(function () {
      ticking = false;
      var probe = 150;
      var idx = 0;
      for (var i = 0; i < total; i++) {
        if (spreads[i].getBoundingClientRect().top <= probe) idx = i;
      }
      if (idx !== cur) {
        cur = idx;
        updateUI();
        if (history.replaceState) {
          try { history.replaceState(null, "", "#p" + cur); } catch (e) {}
        }
      }
    });
  }, { passive: true });

  if (prevBtn) prevBtn.addEventListener("click", prev);
  if (nextBtn) nextBtn.addEventListener("click", next);
  if (track) track.addEventListener("click", function (e) {
    var r = track.getBoundingClientRect();
    var ratio = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    goTo(Math.round(ratio * (total - 1)));
  });

  if (modeBtn) modeBtn.addEventListener("click", function () {
    single = !single;
    root.classList.toggle("single", single);
    modeBtn.textContent = single ? "连续阅读" : "单页翻页";
    goTo(cur, false);
    if (single) preload(cur);
  });

  // 直达某页：#p12 或 #12。浏览器对锚点的初始滚动会在懒加载图片陆续到位后失效，
  // 所以取消它的恢复行为，改由脚本在几个时间点统一定位（用户一动就不管了）。
  var raw = (location.hash || "").replace("#", "");
  var m = /^p?(\d+)$/.exec(raw);
  if (m) {
    var target = Math.max(0, Math.min(total - 1, parseInt(m[1], 10)));
    cur = target;
    updateUI();
    try { history.scrollRestoration = "manual"; } catch (e) {}
    if (raw.charAt(0) !== "p") {
      try { history.replaceState(null, "", "#p" + target); } catch (e) {}
    }
    var userScrolled = false;
    var markUser = function () { userScrolled = true; };
    ["wheel", "touchmove"].forEach(function (ev) {
      window.addEventListener(ev, markUser, { passive: true, once: true });
    });
    var doAlign = function () {
      var el = spreads[target];
      if (!el || userScrolled || userNavigated) return;
      var html = document.documentElement;
      var prev = html.style.scrollBehavior;
      html.style.scrollBehavior = "auto";
      window.scrollTo(0, el.getBoundingClientRect().top + window.pageYOffset - 62);
      html.style.scrollBehavior = prev;
      updateUI();
    };
    [80, 400, 900, 1500, 2400].forEach(function (t) { window.setTimeout(doAlign, t); });
    window.addEventListener("load", function () { window.setTimeout(doAlign, 120); });
  } else {
    updateUI();
  }
})();
