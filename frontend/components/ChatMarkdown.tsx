"use client";
/**
 * 채팅 말풍선용 마크다운 렌더러 — OP-FE features/chat/components/ChatMarkdown.tsx 그대로. GFM(표·취소선·체크박스) 지원.
 * 패널 폭이 320px 이라 여백을 촘촘하게 잡고, 표·코드는 가로 스크롤로 넘친다.
 * HTML 은 렌더하지 않는다(react-markdown 기본) — LLM 출력이라 안전하게.
 */
import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

const components: Components = {
  p: ({ children }) => <p className="my-1.5 first:mt-0 last:mb-0">{children}</p>,
  h1: ({ children }) => <h3 className="mb-1 mt-3 text-sm font-semibold first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="mb-1 mt-3 text-sm font-semibold first:mt-0">{children}</h3>,
  h3: ({ children }) => <h4 className="mb-1 mt-2.5 text-sm font-semibold first:mt-0">{children}</h4>,
  h4: ({ children }) => <h5 className="mb-1 mt-2 text-[13px] font-semibold first:mt-0">{children}</h5>,
  ul: ({ children }) => <ul className="my-1.5 list-disc space-y-0.5 pl-4">{children}</ul>,
  ol: ({ children }) => <ol className="my-1.5 list-decimal space-y-0.5 pl-4">{children}</ol>,
  li: ({ children }) => <li className="[&>p]:my-0">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-neutral-900">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer noopener" className="text-primary underline underline-offset-2">
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-1.5 border-l-2 border-neutral-300 pl-2.5 text-neutral-600">{children}</blockquote>
  ),
  hr: () => <hr className="my-2 border-neutral-200" />,
  code: ({ className, children, ...props }) => {
    // 블록 코드는 language-* 클래스가 붙어 온다. 인라인은 없다.
    const isBlock = /language-/.test(className ?? "") || String(children).includes("\n");
    if (isBlock) {
      return (
        <code className={cn("block whitespace-pre font-mono text-[12px] leading-5", className)} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code className="rounded bg-neutral-100 px-1 py-0.5 font-mono text-[12px] text-neutral-800" {...props}>
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="my-1.5 overflow-x-auto rounded-md border border-neutral-200 bg-neutral-50 px-2.5 py-2">{children}</pre>
  ),
  table: ({ children }) => (
    <div className="my-1.5 overflow-x-auto rounded-md border border-neutral-200">
      <table className="min-w-full border-collapse text-[12px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-neutral-50">{children}</thead>,
  tr: ({ children }) => <tr className="last:[&>td]:border-b-0">{children}</tr>,
  th: ({ children }) => (
    <th className="whitespace-nowrap border-b border-neutral-200 px-2 py-1 text-left text-[11px] font-medium uppercase tracking-wider text-neutral-500">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="whitespace-nowrap border-b border-neutral-100 px-2 py-1 align-top font-mono tabular-nums">{children}</td>
  ),
};

// 굵게 안쪽 끝이 문장부호인데 바깥에 한글 조사가 바로 붙으면('**「발표 일정」**에') CommonMark 가 굵게로 못 닫아 별표가 그대로 보인다 —
// 안쪽 끝에 폭 없는 공백을 끼워 닫히게 한다
const fixBold = (s: string) => s.replace(/\*\*([^*\n]+?)\*\*/g, (m, inner: string) => (/^[\p{P}\p{S}]|[\p{P}\p{S}]$/u.test(inner) ? `**​${inner}​**` : m));

function ChatMarkdownImpl({ content, className, components: extra }: { content: string; className?: string; components?: Partial<Components> }) {
  return (
    <div className={cn("text-sm leading-relaxed text-neutral-800 [word-break:break-word]", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={extra ? { ...components, ...extra } : components}>
        {fixBold(content)}
      </ReactMarkdown>
    </div>
  );
}

// 스트리밍 중 델타마다 부모가 리렌더되므로 content 가 같으면 건너뛴다(components 를 넘기는 쪽은 useMemo 로 같은 객체를 유지할 것).
const ChatMarkdown = memo(ChatMarkdownImpl);
export default ChatMarkdown;
