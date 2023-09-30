const defaultTheme = require('tailwindcss/defaultTheme')

module.exports = {
    darkMode: 'class',
    content: ["./games/**/*.{html,js}"],
    theme: {
        extend: {
          fontFamily: {
            'sans': ['IBM Plex Sans', ...defaultTheme.fontFamily.sans],
            'mono': ['IBM Plex Mono', ...defaultTheme.fontFamily.mono],
          }
        },
    },
    plugins: [
        require('@tailwindcss/typography'),
        require('@tailwindcss/forms')
    ],
}
