// preload.ts — Bun plugin for loading .mdx files as template functions
//
// Converts MDX prompt templates into functions that interpolate {props.X} patterns

import { plugin } from "bun";

plugin({
  name: "mdx-loader",
  setup(build) {
    build.onLoad({ filter: /\.mdx$/ }, async (args) => {
      const text = await Bun.file(args.path).text();
      // Export MDX as a function component that interpolates props
      const code = `
        export default function MDXPrompt(props) {
          let text = ${JSON.stringify(text)};
          // Replace {props.X} patterns with actual values
          for (const [key, value] of Object.entries(props)) {
            text = text.replaceAll(\`{props.\${key}}\`, String(value ?? ""));
          }
          return text;
        }
      `;
      return { contents: code, loader: "ts" };
    });
  },
});
