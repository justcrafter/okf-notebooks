// Applies the saved theme before first paint (a classic script: the CSP forbids inline ones).
try {
  var t = localStorage.getItem("okf-theme");
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
} catch (e) {}
