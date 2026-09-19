'use client';

import { useState } from 'react';
import { BookOpen } from 'lucide-react';
import { summarizeKnowledge, type KnowledgeSource } from '@/lib/knowledge-summary';

type WikiExcerpt = { summary: string; citation: { document_id: string; quote: string } };

export function KnowledgeOverview({ sources, checkedIds, claims = [] }: { sources?: KnowledgeSource[]; checkedIds?: string[]; claims?: WikiExcerpt[] }) {
  const [selectedId, setSelectedId] = useState('MINUTES-01');
  const summary = sources ? summarizeKnowledge(sources) : null;
  const selected = sources?.find(source => source.id === selectedId) || sources?.[0];
  const excerpts = claims.filter(claim => claim.citation.document_id === selected?.id && checkedIds?.includes(claim.citation.document_id));
  const scope = (selected?.body || '').split('\n').filter(line => /^(客户|订单|版本|物料|替代|批次|数量上限|决定)[：:]/.test(line));
  const checked = new Set((checkedIds || []).filter(id => id !== 'MAIL-DELAY' && sources?.some(source => source.id === id))).size;
  return <section className="wiki-knowledge-overview" aria-label="当前知识库">
    <div className="wiki-knowledge-heading">
      <h2><BookOpen size={20} />知识库</h2>
      <span>{summary ? `共 ${summary.total} 份资料` : '正在读取资料…'}</span>
    </div>
    {summary && <div className="wiki-knowledge-counts">
      {summary.groups.map(group => <div key={group.label}>
        <span>{group.label}</span><strong>{group.sources.length}<small>{group.unit}</small></strong>
      </div>)}
    </div>}
    {checkedIds && <p className="wiki-knowledge-checked">本次已核对 <strong>{checked}</strong> 份资料 <span>· 按实际查询记录统计，不代表全部有效或已获批准</span></p>}
    <details>
      <summary>打开知识库 · 浏览目录与内容</summary>
      <p>选择一份资料，查看内容与出处。目录包含不同测试情境的资料，不代表它们都适用于当前订单。</p>
      <div className="wiki-library">
        <nav aria-label="知识库资料目录">
          {summary?.groups.map(group => <div className="wiki-knowledge-directory" key={group.label}>
            <strong>{group.label} · {group.sources.length}</strong>
            {group.sources.length ? <ul>{group.sources.map(source => <li key={source.id}>
              <button type="button" aria-pressed={selected?.id === source.id} aria-controls="wiki-library-reader" onClick={() => setSelectedId(source.id)}>{source.title.replace(/（模拟[^）]*）/g, '')}</button>
            </li>)}</ul> : <p>暂无资料</p>}
          </div>)}
        </nav>
        <article id="wiki-library-reader" className="wiki-library-reader" aria-label="资料正文" aria-live="polite">
          {selected ? <>
            <span className="wiki-library-label">{selected.id === 'MAIL-DELAY' ? '归档样例 · 不参与本次分析' : checkedIds?.includes(selected.id) ? '本次已核对' : '资料库条目 · 本次尚未核对'}</span>
            <h3>{selected.title.replace(/（模拟[^）]*）/g, '')}</h3>
            {!!scope.length && <><h4>资料标明的适用范围与结论</h4><div className="wiki-library-scope">{scope.map(line => <span key={line}>{line}</span>)}</div></>}
            {!!excerpts.length && <><h4>本次知识库 提取的要点</h4>{excerpts.map((claim, index) => <div key={index} className="wiki-library-excerpt"><p>{claim.summary}</p><blockquote>{claim.citation.quote}</blockquote></div>)}</>}
            <h4>原始记录全文</h4>
            <pre>{selected.body || '该资料暂无可展示的正文。'}</pre>
            <small>来源编号：{selected.id} · 模拟资料原文；目录展示不等于批准使用。</small>
          </> : <p>资料加载后即可浏览。</p>}
        </article>
      </div>
    </details>
  </section>;
}
