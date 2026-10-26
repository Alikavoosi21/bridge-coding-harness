// Sync the user's approved design-system artwork. This does not design a logo.
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const sharp = require('sharp');
const root = path.resolve(__dirname, '..');
(async()=>{
  const source=path.join(root,'docs/design-reference');
  const brand=path.join(root,'public/brand'),motion=path.join(root,'public/motion');
  fs.mkdirSync(brand,{recursive:true});fs.mkdirSync(motion,{recursive:true});
  for(const [input,output] of [['bridge-symbol-brand.svg','approved-bridge.svg'],['bridge-symbol-white.svg','approved-bridge-white.svg'],['bridge-app-icon.svg','approved-bridge-app.svg']]){
    const svg=fs.readFileSync(path.join(source,'brand',input),'utf8').replaceAll('Onboard Harness Bridge','Bridge Coding Harness — approved Bridge');
    fs.writeFileSync(path.join(brand,output),svg);
  }
  const svg=fs.readFileSync(path.join(brand,'approved-bridge-app.svg'));
  const png=await sharp(svg).resize(512,512).png().toBuffer();
  for(const name of ['build/icon.png','build/bridge-icon.png','electron/icon.png','electron/bridge-icon.png','src/app/icon.png','src/app/apple-icon.png','public/brand/approved-bridge-app.png'])fs.writeFileSync(path.join(root,name),png);
  for(const state of ['loading','executing','correcting','approval','success']){
    for(const suffix of ['.gif','-poster.png'])fs.copyFileSync(path.join(source,'motion',state+suffix),path.join(motion,'bridge-'+state+suffix));
  }
  const python=path.join(root,'backend/.venv/Scripts/python.exe');
  const result=spawnSync(python,['-c',"from PIL import Image; from pathlib import Path; r=Path('.'); im=Image.open(r/'build/bridge-icon.png'); [im.save(r/p,format='ICO',bitmap_format='bmp',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]) for p in ['build/icon.ico','build/bridge-icon.ico','electron/bridge-icon.ico']]"],{cwd:root,stdio:'inherit'});
  if(result.status!==0)throw Error('ICO export failed');
  for(const directory of [brand,motion])for(const name of fs.readdirSync(directory))if(name.startsWith('coding-'))fs.unlinkSync(path.join(directory,name));
  console.log('Approved Bridge geometry, colors and GIFs synced to UI, Next, Windows and installer icons.');
})().catch(error=>{console.error(error);process.exitCode=1});
