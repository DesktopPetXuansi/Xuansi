import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
export default defineConfig([
  ...nextVitals,
  ...nextTs,
  // 正式与验收构建目录均为生成产物，不参与源码检查。
  globalIgnores([".next*/**", "next-env.d.ts"]),
  { rules: { "@typescript-eslint/no-explicit-any": "error" } },
]);
