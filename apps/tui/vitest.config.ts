import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    setupFiles: [],
    globals: true,
  },
  esbuild: {
    // Ink v5 uses JSX "react-jsx" transform
    jsx: "automatic",
    jsxImportSource: "react",
  },
});
