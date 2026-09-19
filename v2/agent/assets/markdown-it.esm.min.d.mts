/** The consumed subset of the vendored markdown-it API. */
export interface Token {
  content: string;
  type: string;
  attrSet(name: string, value: string): void;
  attrGet(name: string): string | null;
}
export interface Options { html: boolean; linkify: boolean }
export interface Renderer {
  rules: Record<string, (tokens: Token[], index: number, options: Options, environment: unknown, renderer: Renderer) => string>;
  renderToken(tokens: Token[], index: number, options: Options, environment: unknown): string;
}
export default function markdownit(options: Options): {
  validateLink(url: string): boolean;
  renderer: Renderer;
  utils: { escapeHtml(value: string): string };
  render(text: string): string;
};
