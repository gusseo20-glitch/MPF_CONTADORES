(function () {
  'use strict';

  function initAccordion() {
    var items = document.querySelectorAll('details.accordion-item');
    if (!items.length) return;

    // Open first item by default
    if (!window.location.hash) {
      items[0].setAttribute('open', '');
    }

    // Open item matching URL hash
    if (window.location.hash) {
      var target = document.querySelector(window.location.hash);
      if (target) {
        var parentDetails = target.closest('details.accordion-item');
        if (parentDetails) parentDetails.setAttribute('open', '');
        setTimeout(function () { target.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 100);
      }
    }

    // Wire up table row clicks to open matching accordion
    document.querySelectorAll('.model-table').forEach(function (table) {
      table.addEventListener('click', function (e) {
        var row = e.target.closest('tr[data-method]');
        if (!row) return;
        var methodId = row.getAttribute('data-method');
        var targetDetails = document.getElementById(methodId);
        if (!targetDetails) return;
        items.forEach(function (d) { if (d !== targetDetails) d.removeAttribute('open'); });
        targetDetails.setAttribute('open', '');
        targetDetails.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  }

  document.addEventListener('DOMContentLoaded', initAccordion);
})();
