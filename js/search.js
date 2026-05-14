(function () {
  'use strict';

  /* ── Per-page table filter ── */
  function initTableSearch() {
    var input = document.getElementById('table-search');
    var select = document.getElementById('table-filter');
    var table = document.getElementById('model-table');
    var noResults = document.getElementById('table-no-results');
    if (!input || !table) return;

    function filter() {
      var query = input.value.trim().toLowerCase();
      var method = select ? select.value : '';
      var rows = table.querySelectorAll('tbody tr');
      var visible = 0;

      rows.forEach(function (row) {
        var text = row.textContent.toLowerCase();
        var matchQuery = !query || text.includes(query);
        var matchMethod = !method || (row.getAttribute('data-method') === method);
        var show = matchQuery && matchMethod;
        row.hidden = !show;
        if (show) visible++;
      });

      if (noResults) noResults.hidden = visible > 0;
    }

    input.addEventListener('input', filter);
    if (select) select.addEventListener('change', filter);
  }

  /* ── Global search (index.html) ── */
  function initGlobalSearch() {
    var input = document.getElementById('global-search');
    var panel = document.getElementById('search-results-panel');
    var list = document.getElementById('search-results-list');
    var grid = document.getElementById('brand-grid');
    if (!input || !panel || !list) return;

    var data = window.__allModels || [];

    input.addEventListener('input', function () {
      var query = this.value.trim().toLowerCase();

      if (!query) {
        panel.hidden = true;
        if (grid) grid.hidden = false;
        list.innerHTML = '';
        return;
      }

      if (grid) grid.hidden = true;

      var matches = data.filter(function (item) {
        return item.model.toLowerCase().includes(query) ||
          item.brand.toLowerCase().includes(query);
      });

      if (!matches.length) {
        list.innerHTML = '<div class="search-no-results">No se encontraron modelos para "<strong>' + escapeHtml(query) + '</strong>".</div>';
        panel.hidden = false;
        return;
      }

      list.innerHTML = matches.map(function (item) {
        return '<a href="marcas/' + item.brandSlug + '.html" class="search-result-item">' +
          '<span class="search-result-item__model">' + escapeHtml(item.model) + '</span>' +
          '<span class="search-result-item__meta">' + escapeHtml(item.brand) + ' &mdash; ' + escapeHtml(item.method) + '</span>' +
          '</a>';
      }).join('');

      panel.hidden = false;
    });
  }

  function escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  document.addEventListener('DOMContentLoaded', function () {
    initTableSearch();
    initGlobalSearch();
  });
})();
