// Applies the visitor's theme before first paint, so there is no flash.
// Externalised from the template's inline <script> on purpose: this site sets a
// Content-Security-Policy with script-src 'self', and an inline script would
// need a hash that silently stops matching the moment anyone edits the line.
(function () {
  var m = location.search.match(/[?&]theme=([\w-]+)/)
    || document.cookie.match(/(?:^|;\s*)neo_theme=([\w-]+)/);
  if (m && m[1] !== 'default') document.documentElement.dataset.theme = decodeURIComponent(m[1]);
})();
