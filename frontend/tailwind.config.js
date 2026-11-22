/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { 50: "#eef8f0", 100: "#d6eedb", 200: "#addcb8", 300: "#7cc48e", 400: "#4ea965", 500: "#2f9e44", 600: "#1f7a3d", 700: "#1a6233", 800: "#164e2b", 900: "#103a20" },
        water: { 50: "#eef6fd", 100: "#d4e9fa", 300: "#7cc4ff", 500: "#1c6fb8", 600: "#185f9e", 700: "#134c7f" },
        sun: { 100: "#fff4d6", 400: "#f6b93b", 600: "#c98a06" },
        ink: { 400: "#7a8a80", 500: "#5b6b61", 700: "#2e3a33", 900: "#16201a" },
        danger: { 50: "#fdeeee", 500: "#d64545", 700: "#a32c2c" },
      },
      fontFamily: { sans: ["Inter", "Noto Kufi Arabic", "system-ui", "sans-serif"], arabic: ["Noto Kufi Arabic", "Inter", "sans-serif"] },
      boxShadow: { card: "0 1px 2px rgba(16,58,32,.06), 0 4px 16px rgba(16,58,32,.06)" },
      borderRadius: { xl2: "1.1rem" },
    },
  },
  plugins: [],
};
