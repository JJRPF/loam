// Builds the contact link in the browser so the address is not sitting in the page source as plain text.
// Without JavaScript the page shows "jjrpfister at gmail dot com".
(function () {
  var user = 'jjrpfister', host = 'gmail' + '.' + 'com';
  var addr = user + '@' + host;
  var nodes = document.querySelectorAll('[data-contact]');
  for (var i = 0; i < nodes.length; i++) {
    var a = document.createElement('a');
    a.href = 'mailto:' + addr;
    a.textContent = addr;
    nodes[i].replaceChildren(a);
  }
})();
