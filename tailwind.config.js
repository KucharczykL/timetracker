const defaultTheme = require('tailwindcss/defaultTheme')
const colors = require('tailwindcss/colors');

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
      },
      colors: {
        'accent': colors.violet[600],
        'background': colors.gray[800],
      }
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
    require('@tailwindcss/forms'),
    require('flowbite/plugin')
  ],
}
