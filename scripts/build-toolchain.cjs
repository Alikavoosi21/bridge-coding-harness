const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process');
const root=path.resolve(__dirname,'..'),target=path.join(root,'build/toolchain');
const python=path.join(root,'backend/.venv/Scripts/python.exe');
const base=cp.execFileSync(python,['-c','import sys;print(sys.base_prefix)'],{encoding:'utf8'}).trim();
fs.mkdirSync(target,{recursive:true});
const py=path.join(target,'python');fs.mkdirSync(py,{recursive:true});
for(const name of ['python.exe','python3.dll','python311.dll','LICENSE.txt','DLLs','Lib']){
 const source=path.join(base,name);if(!fs.existsSync(source))continue;
 fs.cpSync(source,path.join(py,name),{recursive:true,filter:p=>!p.split(path.sep).some(s=>['site-packages','__pycache__','test','tests','idlelib','tkinter'].includes(s))});
}
const pip=path.join(root,'backend/.venv/Lib/site-packages/pip');if(fs.existsSync(pip))fs.cpSync(pip,path.join(py,'Lib/site-packages/pip'),{recursive:true,filter:p=>!p.split(path.sep).includes('__pycache__')});
for(const name of fs.readdirSync(base).filter(n=>/^(vcruntime.*|python\d*)\.dll$/i.test(n)))fs.copyFileSync(path.join(base,name),path.join(py,name));
const node=path.dirname(process.execPath),nodeTarget=path.join(target,'node');fs.mkdirSync(nodeTarget,{recursive:true});
fs.copyFileSync(process.execPath,path.join(nodeTarget,'node.exe'));
for(const name of ['npm.cmd','npx.cmd'])fs.copyFileSync(path.join(node,name),path.join(nodeTarget,name));
fs.cpSync(path.join(node,'node_modules/npm'),path.join(nodeTarget,'node_modules/npm'),{recursive:true});
cp.execFileSync(path.join(py,'python.exe'),['-c','import ssl,json,venv,http.server;print("BUNDLED_PYTHON_OK")'],{stdio:'inherit'});
cp.execFileSync(path.join(nodeTarget,'node.exe'),[path.join(nodeTarget,'node_modules/npm/bin/npm-cli.js'),'--version'],{stdio:'inherit'});
console.log('Bundled tools ready');
