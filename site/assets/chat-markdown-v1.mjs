import markdownit from "./markdown-it-15.0.0/markdown-it.esm.min.mjs";

/**
 * Assistant Markdown contract: paragraphs, emphasis, headings, lists, HTTPS
 * links, inline/fenced code, blockquotes, horizontal rules, and tables.
 * Model output is untrusted: raw HTML, images, and automatic links stay off.
 */
const markdown = markdownit({
  html: false,
  linkify: false
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

const linkHasVisibleText = (tokens, index) => {
  for (
    let next = index + 1;
    next < tokens.length && tokens[next].type !== "link_close";
    next++
  ) {
    if (tokens[next].content.replace(/[\s\p{Cf}]/gu, "")) return true;
  }
  return false;
};

markdown.renderer.rules.link_open = (tokens, index, options, environment, renderer) => {
  const token = tokens[index];
  token.attrSet("target", "_blank");
  token.attrSet("rel", "noopener noreferrer");
  const openingTag = renderer.renderToken(tokens, index, options, environment);
  if (linkHasVisibleText(tokens, index)) return openingTag;
  return openingTag + markdown.utils.escapeHtml(token.attrGet("href"));
};

export const renderAssistantMarkdown = (text) => markdown.render(text);
