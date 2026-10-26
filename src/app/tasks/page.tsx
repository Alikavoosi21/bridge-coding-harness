'use client';
import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { TaskView } from '@/features/tasks/task-view';
import { TaskList } from '@/features/tasks/task-list';
import { ChangesReview } from '@/features/changes/review';
import { ApplyResult } from '@/features/changes/result';
function Tasks() {
  const params=useSearchParams();
  const taskId=params.get('task');
  const operationId=params.get('operation');
  if(taskId&&operationId&&params.get('view')==='result')return <ApplyResult key={operationId} taskId={taskId} operationId={operationId}/>;
  return taskId ? params.get('view')==='changes'?<ChangesReview key={taskId} taskId={taskId} initialPath={params.get('file')}/>:<TaskView key={taskId} taskId={taskId} /> : <TaskList />;
}
export default function Page() { return <Suspense fallback={<p className="p-6">در حال خواندن کار…</p>}><Tasks /></Suspense>; }
