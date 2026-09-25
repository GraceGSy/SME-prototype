import { build } from "esbuild";
import { mkdirSync, writeFileSync } from "node:fs";
import { z } from "zod";
import { manifestSchema, paperSchema, snapshotSchema } from "./src/contracts";

const out = "pipeline/viewer/dist";
mkdirSync(out, { recursive: true });
await build({
  entryPoints: ["pipeline/viewer/src/app.ts"],
  bundle: true,
  minify: true,
  format: "esm",
  target: "es2022",
  outfile: out + "/app.js",
});
// Python packaging and the browser validate the same wire schema.
writeFileSync(
  out + "/contracts.json",
  JSON.stringify(
    Object.fromEntries(
      Object.entries({
        manifest: manifestSchema,
        paper: paperSchema,
        snapshot: snapshotSchema,
      }).map(([name, schema]) => [name, z.toJSONSchema(schema)]),
    ),
    null,
    2,
  ) + "\n",
);
