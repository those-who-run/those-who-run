// ADR 0004 point 1, as an ESLint rule: style comes from the tokens in src/styles/,
// so code elsewhere in src/ may not carry a colour literal (hex, rgb(), hsl(),
// oklch()…), a Tailwind arbitrary value (`text-[#f00]`, `p-[13px]`, `[mask:none]`)
// or a literal in a `style={{…}}` prop. eslint.config.js applies it to src/ outside
// src/styles/; scripts/lint-rules.test.ts checks it.
import type { ESLint, Rule } from "eslint";

const HEX = /(?:^|[^\w&])#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})(?![\w-])/i;
const COLOUR_FUNCTION = /\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(/i;
// `p-[13px]`, `text-[#f00]`, `w-[calc(100%-1rem)]/50`, but not a variant such as
// `data-[state=open]:` (followed by a colon) or a CSS variable `p-(--gutter)`.
const ARBITRARY_VALUE = /(?:^|[\s:!])-?[a-z][\w-]*-\[[^\]\s]+\](?:\/\S+)?(?=$|\s)/;
const ARBITRARY_PROPERTY = /(?:^|[\s:!])\[[a-z-]+:[^\]\s]+\](?=$|\s)/;

/** Why a string is not allowed outside src/styles/, or null when it is fine. */
export function styleLiteral(text: string): string | null {
  if (HEX.test(text) || COLOUR_FUNCTION.test(text)) {
    return "a colour literal";
  }
  if (ARBITRARY_VALUE.test(text) || ARBITRARY_PROPERTY.test(text)) {
    return "an arbitrary Tailwind value";
  }
  return null;
}

const HINT = "use a token from src/styles/tokens.css (ADR 0004 point 1), or add one there";

const noStyleLiterals: Rule.RuleModule = {
  meta: {
    type: "problem",
    docs: { description: "Style only through the design tokens (ADR 0004 point 1)" },
    schema: [],
  },
  create(context) {
    const check = (node: Rule.Node, text: string) => {
      const what = styleLiteral(text);
      if (what) {
        context.report({ node, message: `${what} (${JSON.stringify(text)}) outside src/styles/: ${HINT}` });
      }
    };
    return {
      Literal(node) {
        if (typeof node.value === "string") {
          check(node, node.value);
        }
      },
      TemplateElement(node) {
        check(node, node.value.cooked ?? node.value.raw);
      },
      // style={{ color: x, padding: 13 }}: a literal value there is a style the
      // tokens don't know. A computed value (a chart's width) is fine.
      "JSXAttribute[name.name='style'] > JSXExpressionContainer > ObjectExpression > Property > Literal.value"(
        node: Rule.Node,
      ) {
        const value = node.type === "Literal" ? node.value : null;
        if (typeof value === "string" && styleLiteral(value)) {
          return; // reported once already, as the literal it is
        }
        context.report({ node, message: `a literal in a style prop outside src/styles/: ${HINT}` });
      },
    };
  },
};

export const styleLiteralsPlugin: ESLint.Plugin = {
  meta: { name: "twr-style" },
  rules: { "no-style-literals": noStyleLiterals },
};
