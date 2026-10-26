// Electron's default CompanyName survives an empty author; remove it before packaging.
const fs=require('node:fs');
const path=require('node:path');
const {NtExecutable,NtExecutableResource,Resource}=require('resedit');

module.exports=async({appOutDir,packager,electronPlatformName})=>{
  if(electronPlatformName!=='win32'||packager.appInfo.companyName)return;
  const file=path.join(appOutDir,packager.appInfo.productFilename+'.exe');
  const exe=NtExecutable.from(fs.readFileSync(file));
  const resources=NtExecutableResource.from(exe);
  for(const version of Resource.VersionInfo.fromEntries(resources.entries)){
    for(const language of version.getAllLanguagesForStringValues()){
      version.removeStringValue(language,'CompanyName');
      if(packager.appInfo.copyright==='')version.removeStringValue(language,'LegalCopyright');
    }
    version.outputToResourceEntries(resources.entries);
  }
  resources.outputResource(exe);
  fs.writeFileSync(file,Buffer.from(exe.generate()));
};
