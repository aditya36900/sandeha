/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // RGB channels so opacity modifiers like bg-ink/60 work
      colors: Object.fromEntries(
        ['ink', 'surface', 'raised', 'line', 'bone', 'mist', 'pass', 'fail', 'doubt', 'hold']
          .map(c => [c, `rgb(var(--${c}-rgb) / <alpha-value>)`])
      ),
      fontFamily: {
        sans: ['"IBM Plex Sans Condensed"', 'system-ui', 'sans-serif'],
        voice: ['"Instrument Serif"', 'Georgia', 'serif']
      }
    }
  },
  plugins: []
};
