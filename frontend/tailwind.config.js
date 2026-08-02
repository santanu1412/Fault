/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Power grid status colors
        grid: {
          live: '#22c55e',       // Green — energized pole
          dark: '#ef4444',       // Red — confirmed dark
          suspect: '#f97316',    // Orange — sensor suspect
          unknown: '#6b7280',    // Gray — no device / unknown
          boundary: '#eab308',   // Yellow — fault boundary line
          inferred: '#a78bfa',   // Purple — inferred topology
        },
        // UI chrome colors (dark ops console)
        surface: {
          900: '#0a0e17',       // Deepest background
          800: '#111827',       // Panel background
          700: '#1e293b',       // Card background
          600: '#334155',       // Elevated surface
          500: '#475569',       // Borders
        },
        accent: {
          primary: '#3b82f6',    // Blue — primary actions
          danger: '#ef4444',     // Red — critical
          warning: '#f59e0b',    // Amber — warnings
          success: '#10b981',    // Emerald — success
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-in': 'slideIn 0.3s ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideIn: {
          '0%': { transform: 'translateX(20px)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
      },
    },
  },
  plugins: [],
};
