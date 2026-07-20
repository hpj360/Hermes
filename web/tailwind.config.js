/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#fdf6ec",
          100: "#faecd3",
          500: "#d4a44f",
          600: "#b8862d",
          700: "#8c6420",
        },
      },
    },
  },
  plugins: [],
};
