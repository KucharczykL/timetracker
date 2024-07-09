const defaultTheme = require('tailwindcss/defaultTheme')

module.exports = {
  darkMode: 'class',
  content: ["./games/**/*.{html,js}", './node_modules/flowbite/**/*.js'],
  theme: {
    extend: {
      fontFamily: {
        'sans': ['IBM Plex Sans', ...defaultTheme.fontFamily.sans],
        'mono': ['IBM Plex Mono', ...defaultTheme.fontFamily.mono],
        'serif': ['IBM Plex Serif', ...defaultTheme.fontFamily.serif],
        'condensed': ['IBM Plex Sans Condensed', ...defaultTheme.fontFamily.sans],
      }
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
    require('@tailwindcss/forms'),
    require('flowbite/plugin')
  ],
}
