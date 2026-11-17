import type { Config } from "tailwindcss";

/** Palette entries resolve to a CSS variable, so opacity modifiers still work. */
const themed = (variable: string) => `rgb(var(${variable}) / <alpha-value>)`;

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./components/views/**/*.{ts,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
        arabic: ["var(--font-arabic)", "serif"],
      },
      colors: {
        /* Semantic names introduced by the Bolt design refresh. */
        app: themed("--bg-rgb"),
        surface: {
          DEFAULT: themed("--surface-rgb"),
          elevated: themed("--surface-elevated-rgb"),
        },
        primary: {
          50: "#eff4ff",
          100: "#dbe6ff",
          200: "#bed2ff",
          300: "#91b4ff",
          400: "#5d8dff",
          500: "#3272ff",
          600: "#1c52f5",
          700: "#143ce1",
          800: "#1632b8",
          900: "#182e91",
          950: "#0d1a56",
        },
        neutral: {
          25: "#fbfbfd",
          50: "#f8fafc",
          100: "#f1f5f9",
          200: "#e2e8f0",
          300: "#cbd5e1",
          400: "#94a3b8",
          500: "#64748b",
          600: "#475569",
          700: "#334155",
          800: "#1e293b",
          900: "#0f172a",
          950: "#020617",
        },
        success: {
          500: "#10b981",
          600: "#059669",
        },
        warning: {
          500: "#f59e0b",
          600: "#d97706",
        },
        error: {
          500: "#ef4444",
          600: "#dc2626",
        },

        /* Legacy names kept so untouched components still compile. */
        ink: {
          900: themed("--bg-rgb"),
          800: themed("--surface-rgb"),
          700: themed("--surface-raised-rgb"),
        },
        white: themed("--white-rgb"),
        slate: {
          100: themed("--slate-100-rgb"),
          200: themed("--slate-200-rgb"),
          300: themed("--slate-300-rgb"),
          400: themed("--slate-400-rgb"),
          500: themed("--slate-500-rgb"),
        },
        accent: {
          400: themed("--accent-400-rgb"),
          500: themed("--accent-500-rgb"),
          600: themed("--accent-600-rgb"),
        },
        emerald: {
          50: themed("--emerald-50-rgb"),
          100: themed("--emerald-100-rgb"),
          200: themed("--emerald-200-rgb"),
          300: themed("--emerald-300-rgb"),
          400: themed("--emerald-400-rgb"),
          500: themed("--emerald-500-rgb"),
          950: themed("--emerald-950-rgb"),
        },
        red: {
          200: themed("--red-200-rgb"),
          300: themed("--red-300-rgb"),
          500: themed("--red-500-rgb"),
        },
        amber: {
          100: themed("--amber-100-rgb"),
          300: themed("--amber-300-rgb"),
          500: themed("--amber-500-rgb"),
        },
        sky: {
          400: themed("--sky-400-rgb"),
        },
      },
      boxShadow: {
        glow: "var(--shadow-glow)",
        menu: "var(--shadow-menu)",
        modal: "var(--shadow-modal)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "slide-in-right": {
          "0%": { transform: "translateX(100%)" },
          "100%": { transform: "translateX(0)" },
        },
        "scale-in": {
          "0%": { opacity: "0", transform: "scale(0.96)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "0.45" },
          "50%": { opacity: "1" },
        },
        progress: {
          "0%": { width: "0%" },
          "100%": { width: "100%" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.25s ease-out",
        "fade-in": "fade-in 0.2s ease-out",
        "fade-in-up": "fade-up 0.35s ease-out both",
        "slide-in-right": "slide-in-right 0.25s ease-out",
        "scale-in": "scale-in 0.2s ease-out",
        "pulse-soft": "pulse-soft 1.4s ease-in-out infinite",
        progress: "progress 1.2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
