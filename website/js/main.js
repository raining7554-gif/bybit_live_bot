/* ============================================================
   DETAILAB — 인터랙션 스크립트 (의존성 없음, 순수 JS)
   ============================================================ */
(function () {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- 부드러운 앵커 스크롤 ---------- */
  document.querySelectorAll("[data-scroll]").forEach((link) => {
    link.addEventListener("click", (e) => {
      const id = link.getAttribute("href");
      if (!id || !id.startsWith("#")) return;
      const target = document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      const top = target.getBoundingClientRect().top + window.scrollY - 64;
      window.scrollTo({ top, behavior: reduceMotion ? "auto" : "smooth" });
      // 모바일 메뉴 닫기
      menu.classList.remove("is-open");
    });
  });

  /* ---------- 네비 상태 + 스크롤 진행 바 ---------- */
  const nav = document.getElementById("nav");
  const progress = document.getElementById("scrollProgress");
  const timelineFill = document.getElementById("timelineFill");
  const timeline = document.getElementById("timeline");

  function onScroll() {
    const y = window.scrollY;
    nav.classList.toggle("is-scrolled", y > 30);

    const docH = document.documentElement.scrollHeight - window.innerHeight;
    progress.style.width = (y / docH) * 100 + "%";

    // 타임라인 진행 채우기
    if (timeline && timelineFill) {
      const r = timeline.getBoundingClientRect();
      const vh = window.innerHeight;
      const total = r.height;
      const passed = Math.min(Math.max(vh * 0.6 - r.top, 0), total);
      timelineFill.style.height = (passed / total) * 100 + "%";
    }
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---------- 모바일 메뉴 ---------- */
  const toggle = document.getElementById("navToggle");
  const menu = document.querySelector(".nav__menu");
  toggle.addEventListener("click", () => menu.classList.toggle("is-open"));

  /* ---------- 스크롤 리빌 (IntersectionObserver) ---------- */
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const el = entry.target;
        const delay = parseInt(el.dataset.delay || "0", 10);
        setTimeout(() => el.classList.add("is-visible"), delay);
        // step 노드 강조
        if (el.classList.contains("step")) el.classList.add("is-visible");
        io.unobserve(el);
      });
    },
    { threshold: 0.15, rootMargin: "0px 0px -8% 0px" }
  );
  document.querySelectorAll(".reveal").forEach((el) => io.observe(el));

  /* ---------- 숫자 카운트업 ---------- */
  const counters = document.querySelectorAll("[data-count]");
  const counterIO = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const el = entry.target;
        const target = parseFloat(el.dataset.count);
        const suffix = el.dataset.suffix || "";
        const dur = 1600;
        const start = performance.now();
        function tick(now) {
          const p = Math.min((now - start) / dur, 1);
          const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
          const val = Math.floor(eased * target);
          el.textContent = val.toLocaleString("ko-KR") + suffix;
          if (p < 1) requestAnimationFrame(tick);
          else el.textContent = target.toLocaleString("ko-KR") + suffix;
        }
        requestAnimationFrame(tick);
        counterIO.unobserve(el);
      });
    },
    { threshold: 0.6 }
  );
  counters.forEach((el) => counterIO.observe(el));

  /* ---------- 포트폴리오 필터 ---------- */
  const filters = document.querySelectorAll(".filter");
  const cards = document.querySelectorAll(".port-grid .card");
  filters.forEach((btn) => {
    btn.addEventListener("click", () => {
      filters.forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      const f = btn.dataset.filter;
      cards.forEach((card) => {
        const show = f === "all" || card.dataset.cat === f;
        card.classList.toggle("is-hidden", !show);
      });
    });
  });

  /* ---------- 히어로 마우스 패럴랙스 ---------- */
  const mockups = document.getElementById("heroMockups");
  if (mockups && !reduceMotion && window.matchMedia("(pointer:fine)").matches) {
    const layers = mockups.querySelectorAll("[data-depth]");
    let raf = null;
    window.addEventListener("mousemove", (e) => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        const cx = (e.clientX / window.innerWidth - 0.5) * 2;
        const cy = (e.clientY / window.innerHeight - 0.5) * 2;
        layers.forEach((l) => {
          const d = parseFloat(l.dataset.depth) * 60;
          l.style.translate = `${-cx * d}px ${-cy * d}px`;
        });
        raf = null;
      });
    });
  }
})();
