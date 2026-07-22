/** @type {import('tailwindcss').Config} */
// C1 重构：删除独立暖金色板，统一引用 design/mockup/_tokens.css 的 CSS 变量。
// 使用方式：在 web/src/index.css 顶部 @import _tokens.css 后，Tailwind 即可通过 var(--*) 取色。
// 注意：Tailwind 的任意值语法 bg-[var(--brand-700)] 总是可用；此处 extend.colors 仅做语义别名。
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 品牌主色（深酒红，与 mockup _tokens.css 完全一致）
        brand: {
          50: "var(--brand-50)",
          100: "var(--brand-100)",
          200: "var(--brand-200)",
          500: "var(--brand-500)",
          700: "var(--brand-700)",
          900: "var(--brand-900)",
        },
        // 暗金强调色
        gold: {
          100: "var(--gold-100)",
          300: "var(--gold-300)",
          500: "var(--gold-500)",
          700: "var(--gold-700)",
        },
        // 暖灰墨色
        ink: {
          50: "var(--ink-50)",
          100: "var(--ink-100)",
          200: "var(--ink-200)",
          400: "var(--ink-400)",
          600: "var(--ink-600)",
          900: "var(--ink-900)",
        },
      },
      fontFamily: {
        serif: ["var(--font-serif)"],
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
      boxShadow: {
        drama: "var(--shadow-drama)",
        gold: "var(--shadow-gold)",
      },
    },
  },
  plugins: [],
};
