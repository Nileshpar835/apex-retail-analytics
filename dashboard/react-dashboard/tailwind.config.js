/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      keyframes: {
        pulseBorder: {
          '0%, 100%': { borderColor: '#ef4444' },
          '50%': { borderColor: '#7f1d1d' },
        },
      },
      animation: {
        'pulse-border': 'pulseBorder 1s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
