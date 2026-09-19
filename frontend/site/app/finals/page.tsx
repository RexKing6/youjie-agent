import type { Metadata } from 'next';
import { WikiWorkbench } from '@/components/wiki-workbench';
import './wiki.css';
import './studio.css';

export const metadata: Metadata = {
  title: '有界｜生产计划助手',
  description: '原料延期后，核对替代件、比较成本与交期，跟进生产任务。',
};

export default function FinalsPage() { return <WikiWorkbench />; }
