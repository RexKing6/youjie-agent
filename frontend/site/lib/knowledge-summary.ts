export type KnowledgeSource = { id: string; title: string; role: string; body?: string };

export function summarizeKnowledge(sources: KnowledgeSource[]) {
  const groups = [
    { label: '会议纪要', unit: '篇', sources: [] as KnowledgeSource[] },
    { label: '历史处理记录', unit: '份', sources: [] as KnowledgeSource[] },
    { label: '邮件', unit: '封', sources: [] as KnowledgeSource[] },
    { label: '聊天记录', unit: '份', sources: [] as KnowledgeSource[] },
    { label: '其他文档', unit: '份', sources: [] as KnowledgeSource[] },
  ];
  // Inventory across all demo scenarios, not the current run's active evidence.
  // One registered source ID is counted once; unknown formats remain visible.
  const unique = [...new Map(sources.map(source => [source.id, source])).values()];
  for (const source of unique) {
    const index = source.title.includes('会议纪要') ? 0
      : source.role === 'history' ? 1
      : source.title.includes('邮件') ? 2
      : source.title.includes('聊天') ? 3 : 4;
    groups[index].sources.push(source);
  }
  return { total: unique.length, groups };
}
