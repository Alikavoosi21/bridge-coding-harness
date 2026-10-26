import { api } from '@/lib/api';

export type AvailableSkill={id?:string;name:string;description?:string;enabled?:boolean;valid?:boolean;changed?:boolean};

export async function availableSkills(taskId?:string,workspaceId?:string|null):Promise<AvailableSkill[]> {
  const route=taskId?`/tasks/${encodeURIComponent(taskId)}/skill-pins`:'/skill-sources'+(workspaceId?'?workspace_id='+encodeURIComponent(workspaceId):'');
  const data=await api.get<{items:AvailableSkill[]}>(route);
  return data.items.filter(item=>taskId?item.valid!==false:item.enabled&&item.valid&&!item.changed);
}
