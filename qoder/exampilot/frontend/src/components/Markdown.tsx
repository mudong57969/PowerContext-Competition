import type { ReactNode } from "react";

function inline(text: string, keyBase: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const token = m[0];
    if (token.startsWith("**")) {
      nodes.push(<strong key={`${keyBase}-s${i++}`}>{token.slice(2, -2)}</strong>);
    } else {
      nodes.push(
        <code key={`${keyBase}-c${i++}`}>{token.slice(1, -1)}</code>,
      );
    }
    last = m.index + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function tableBlock(rows: string[], keyBase: string): ReactNode {
  const cells = rows.map((r) =>
    r
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((c) => c.trim()),
  );
  if (cells.length < 2) return <p key={keyBase}>{rows.join("\n")}</p>;
  const [header, ...body] = cells;
  return (
    <table key={keyBase}>
      <thead>
        <tr>
          {header.map((c, j) => (
            <th key={j}>{inline(c, `${keyBase}-h${j}`)}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {body
          .filter((row) => !row.every((c) => /^:?-+:?$/.test(c)))
          .map((row, i) => (
            <tr key={i}>
              {row.map((c, j) => (
                <td key={j}>{inline(c, `${keyBase}-r${i}c${j}`)}</td>
              ))}
            </tr>
          ))}
      </tbody>
    </table>
  );
}

export default function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let list: { ordered: boolean; items: string[] } | null = null;
  let table: string[] | null = null;

  const flushList = () => {
    if (!list) return;
    const items = list.items.map((item, k) => (
      <li key={k}>{inline(item, `li${blocks.length}-${k}`)}</li>
    ));
    blocks.push(
      list.ordered ? <ol key={`ol${blocks.length}`}>{items}</ol> : <ul key={`ul${blocks.length}`}>{items}</ul>,
    );
    list = null;
  };
  const flushTable = () => {
    if (!table) return;
    blocks.push(tableBlock(table, `tb${blocks.length}`));
    table = null;
  };

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    const heading = /^(#{1,3})\s+(.*)$/.exec(trimmed);
    const orderedItem = /^\d+[.、]\s+(.*)$/.exec(trimmed);
    const bullet = /^[-*]\s+(.*)$/.exec(trimmed);

    if (!trimmed) {
      flushList();
      flushTable();
    } else if (heading) {
      flushList();
      flushTable();
      const level = heading[1].length;
      const Tag = `h${level}` as "h1" | "h2" | "h3";
      blocks.push(<Tag key={`h${i}`}>{inline(heading[2], `h${i}`)}</Tag>);
    } else if (/^\|.*\|$/.test(trimmed)) {
      flushList();
      if (table === null) table = [];
      table.push(trimmed);
    } else if (orderedItem) {
      flushTable();
      if (!list || !list.ordered) {
        flushList();
        list = { ordered: true, items: [] };
      }
      list.items.push(orderedItem[1]);
    } else if (bullet) {
      flushTable();
      if (!list || list.ordered) {
        flushList();
        list = { ordered: false, items: [] };
      }
      list.items.push(bullet[1]);
    } else if (/^```/.test(trimmed)) {
      flushList();
      flushTable();
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i].trim())) {
        code.push(lines[i]);
        i += 1;
      }
      blocks.push(
        <pre key={`p${i}`}>
          <code>{code.join("\n")}</code>
        </pre>,
      );
    } else if (/^>\s?/.test(trimmed)) {
      flushList();
      flushTable();
      blocks.push(
        <blockquote key={`q${i}`}>{inline(trimmed.replace(/^>\s?/, ""), `q${i}`)}</blockquote>,
      );
    } else {
      flushList();
      flushTable();
      blocks.push(<p key={`p${i}`}>{inline(trimmed, `p${i}`)}</p>);
    }
    i += 1;
  }
  flushList();
  flushTable();
  return <div className="prose-exampilot">{blocks}</div>;
}
