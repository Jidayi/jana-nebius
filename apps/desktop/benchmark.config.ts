// A production-optimised, synthetic-only entry; never shipped in the learner bundle.
import { mergeConfig } from "vite";
import desktop from "./vite.config.js";
export default mergeConfig(desktop, {
  build: { outDir: `dist/benchmark${process.env.JANA_GALLERY_BUILD_ID ? `-${process.env.JANA_GALLERY_BUILD_ID}` : ""}`, rolldownOptions: { input: "gallery.html" } },
});
