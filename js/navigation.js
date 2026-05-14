(function () {
  'use strict';

  function initSidebar() {
    var hamburger = document.getElementById('hamburger-btn');
    var sidebar = document.getElementById('sidebar');
    var overlay = document.getElementById('sidebar-overlay');

    if (!hamburger || !sidebar) return;

    function open() {
      sidebar.classList.add('is-open');
      overlay.classList.add('is-open');
      hamburger.setAttribute('aria-expanded', 'true');
    }
    function close() {
      sidebar.classList.remove('is-open');
      overlay.classList.remove('is-open');
      hamburger.setAttribute('aria-expanded', 'false');
    }

    hamburger.addEventListener('click', function () {
      sidebar.classList.contains('is-open') ? close() : open();
    });
    overlay.addEventListener('click', close);

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') close();
    });
  }

  function initActiveLink() {
    var path = window.location.pathname.replace(/\\/g, '/');
    var links = document.querySelectorAll('.sidebar-nav__link');

    links.forEach(function (link) {
      link.removeAttribute('aria-current');
      link.classList.remove('is-active');
    });

    links.forEach(function (link) {
      var href = link.getAttribute('href');
      if (!href) return;

      var normalizedHref = href.replace(/\\/g, '/');
      var isHome = (normalizedHref === 'index.html' || normalizedHref === './index.html');
      var isCurrentHome = (path === '/' || path.endsWith('/index.html') || path.endsWith('/codigos/'));

      if (isHome && isCurrentHome) {
        link.setAttribute('aria-current', 'page');
        link.classList.add('is-active');
        return;
      }

      if (!isHome && path.endsWith(normalizedHref.replace('../', '/').replace('./', '/'))) {
        link.setAttribute('aria-current', 'page');
        link.classList.add('is-active');
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initSidebar();
    initActiveLink();
  });
})();
