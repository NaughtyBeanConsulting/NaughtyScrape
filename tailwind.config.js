/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./scraper/templates/**/*.html",
    // Dynamic badge classes are emitted from template tags:
    "./scraper/templatetags/*.py",
  ],
  // Belt-and-braces: keep status-badge colour classes even if scanning misses them.
  safelist: [
    { pattern: /(bg|text)-(sky|amber|violet|emerald|rose|gray|blue|stone|teal|indigo|fuchsia)-(50|100|200|300|400|500|600|700)/ },
  ],
  theme: {
    extend: {},
  },
  plugins: [require("@tailwindcss/forms")],
};
