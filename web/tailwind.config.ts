import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Confidence palette, reused by badges + chart.
        conf: {
          high: "#16a34a",
          medium: "#d97706",
          low: "#dc2626",
        },
      },
    },
  },
  plugins: [],
};

export default config;
