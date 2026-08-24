/**
 * Markdown da Maya — GFM + highlight de código (rehype-highlight).
 */

import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

export function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          a: (props) => (
            <a
              {...props}
              target="_blank"
              rel="noreferrer"
              className="text-state-listening underline underline-offset-2"
            />
          ),
          code: (props) => {
            const { className, children, ...rest } = props;
            const inline = !className;
            return inline ? (
              <code
                className="border border-line bg-panel px-1 py-px font-mono text-[0.85em] text-state-listening"
                {...rest}
              >
                {children}
              </code>
            ) : (
              <code className={className} {...rest}>
                {children}
              </code>
            );
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
