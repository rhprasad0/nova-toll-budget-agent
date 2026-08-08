import markdownit from "./markdown-it-15.0.0/markdown-it.esm.min.mjs";

/**
 * Assistant Markdown contract: paragraphs, emphasis, headings, lists, HTTPS
 * links, inline/fenced code, blockquotes, horizontal rules, and tables.
 * Model output is untrusted: raw HTML, images, and automatic links stay off.
 */
const markdown = markdownit({
  html: false,
  linkify: false,
  typographer: false
});

markdown.validateLink = (url) => {
  try {
    return new URL(url).protocol === "https:";
  } catch {
    return false;
  }
};

markdown.renderer.rules.image = (tokens, index) =>
  markdown.utils.escapeHtml(tokens[index].content);

markdown.renderer.rules.link_open = (tokens, index, options, environment, renderer) => {
  const token = tokens[index];
  token.attrSet("target", "_blank");
  token.attrSet("rel", "noopener noreferrer");
  return renderer.renderToken(tokens, index, options, environment);
};

export const renderAssistantMarkdown = (text) => markdown.render(text);
