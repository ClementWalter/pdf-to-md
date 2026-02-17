// types.d.ts — Type declarations for MDX module imports
//
// MDX files are loaded via the bun preload plugin and need type declarations

declare module "*.mdx" {
  const MDXComponent: (props: Record<string, any>) => any;
  export default MDXComponent;
}
