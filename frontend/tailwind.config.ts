import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        obsidian: "#0A0E17",
        panel: "#111827",
        cyan: { glow: "#06D6A0" },
        violet: { glow: "#7B61FF" },
      },
      fontFamily: {
        display: ["var(--font-clash)", "system-ui", "sans-serif"],
        body: ["var(--font-satoshi)", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
