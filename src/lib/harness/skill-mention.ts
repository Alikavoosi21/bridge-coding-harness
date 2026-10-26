/** A slash at a word boundary and at the caret, never a path or URL. */
export function skillMention(text:string,caret:number) {
  const prefix=text.slice(0,caret);
  const match=/(?:^|\s)\/([a-z0-9-]*)$/i.exec(prefix);
  if(!match||/[^\s]/.test(text[caret]??''))return null;
  return {query:match[1].toLowerCase(),start:caret-match[1].length-1,end:caret};
}

export function insertSkillMention(text:string,mention:{start:number;end:number},name:string) {
  const inserted=`/${name} `;
  return {text:text.slice(0,mention.start)+inserted+text.slice(mention.end),caret:mention.start+inserted.length};
}
