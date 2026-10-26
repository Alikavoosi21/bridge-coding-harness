const fs=require('node:fs');
const path=require('node:path');
const {spawnSync}=require('node:child_process');

// Explorer may still have the pre-install PATH; use Docker Desktop's registered location.
function dockerEnvironment(env=process.env,{platform=process.platform,exists=fs.existsSync,query=spawnSync}={}){
  if(platform!=='win32')return env;
  const inherited=Object.entries(env).find(([key])=>key.toLowerCase()==='path')?.[1]??'';
  if(inherited.split(';').some(folder=>folder&&exists(path.win32.join(folder.replace(/^"|"$/g,''),'docker.exe'))))return env;
  const candidates=[env.ProgramFiles,env.LOCALAPPDATA].filter(Boolean).map(base=>path.win32.join(base,'Docker','Docker','resources','bin'));
  for(const hive of ['HKLM','HKCU']){
    const result=query('reg',['query',`${hive}\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Docker Desktop`,'/v','InstallLocation'],{encoding:'utf8',windowsHide:true,timeout:2000});
    const location=/InstallLocation\s+REG_(?:EXPAND_)?SZ\s+([^\r\n]+)/.exec(result.stdout??'')?.[1]?.trim();
    if(location&&path.win32.isAbsolute(location))candidates.push(path.win32.join(location,'resources','bin'));
  }
  const folder=candidates.find(candidate=>exists(path.win32.join(candidate,'docker.exe')));
  if(!folder)return env;
  const result={...env};for(const key of Object.keys(result))if(key.toLowerCase()==='path')delete result[key];
  result.PATH=folder+';'+inherited;
  return result;
}
module.exports={dockerEnvironment};
