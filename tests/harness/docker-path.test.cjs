const test=require('node:test'),assert=require('node:assert/strict');
const {dockerEnvironment}=require('../../electron/docker-path.cjs');

test('registered Docker location augments only the engine environment',()=>{
 const input={Path:'C:\\Windows',SECRET_KEY:'not-a-log'};
 const output=dockerEnvironment(input,{platform:'win32',exists:file=>file==='E:\\DockerDesktop\\resources\\bin\\docker.exe',query:()=>({stdout:'InstallLocation    REG_SZ    E:\\DockerDesktop\r\n'})});
 assert.equal(output.PATH,'E:\\DockerDesktop\\resources\\bin;C:\\Windows');assert.equal(output.Path,undefined);
 assert.equal(input.Path,'C:\\Windows');assert.equal(output.SECRET_KEY,input.SECRET_KEY);
});
test('existing PATH and unsupported platforms do not run registry discovery',()=>{
 const input={PATH:'C:\\Docker'};let queries=0;
 const options={platform:'win32',exists:()=>true,query:()=>{queries++;throw Error('unexpected registry access')}};
 assert.equal(dockerEnvironment(input,options),input);assert.equal(queries,0);
 assert.equal(dockerEnvironment(input,{...options,platform:'linux'}),input);
});
