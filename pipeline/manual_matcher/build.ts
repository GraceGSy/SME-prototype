import { build } from "esbuild";
import { cpSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const out = resolve("output/manual-matcher");
const site = out + "/public";
mkdirSync(site + "/samples", { recursive: true });
await build({
  entryPoints: {
    matcher: "pipeline/manual_matcher/app.ts",
    preview: "pipeline/manual_matcher/preview.ts",
    "viewer-app": "pipeline/viewer/src/app.ts",
  },
  outdir: site,
  bundle: true,
  minify: true,
  format: "esm",
  target: "es2022",
});
cpSync("pipeline/manual_matcher/index.html", site + "/index.html");
cpSync("pipeline/manual_matcher/viewer.html", site + "/viewer.html");
cpSync("pipeline/manual_matcher/styles.css", site + "/matcher.css");
cpSync("pipeline/viewer/styles.css", site + "/styles.css");
cpSync("pipeline/viewer/index.html", site + "/viewer-template.html");
const files = ["abstractexplorer", "corpusstudio", "examplore_chi18", "mesotext", "paralib_uist22"];
const titles: Record<string, string> = {
  abstractexplorer: "AbstractExplorer",
  corpusstudio: "CorpusStudio",
  examplore_chi18: "Examplore (CHI 2018)",
  mesotext: "Mesotext",
  paralib_uist22: "Paralib (UIST 2022)",
};
// Ship only the five prepared HCI inputs, never raw sources, runs, or credentials.
const samples = files.map((paper_id) => {
  const filename = paper_id + ".content.json";
  const content = readFileSync("datasets/hci-five-paper/content/" + filename, "utf8");
  writeFileSync(site + "/samples/" + filename, content);
  return { paper_id, title: titles[paper_id], filename, url: "samples/" + filename };
});
writeFileSync(site + "/samples.json", JSON.stringify(samples, null, 2) + "\n");
writeFileSync(
  out + "/package.json",
  JSON.stringify(
    { name: "question-atlas-manual-matcher", private: true, version: "1.0.0" },
    null,
    2,
  ) + "\n",
);
writeFileSync(
  out + "/vercel.json",
  JSON.stringify({ version: 2, framework: null, outputDirectory: "public" }, null, 2) + "\n",
);
console.log("Manual matcher built at " + site);
