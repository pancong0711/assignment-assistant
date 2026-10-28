
import DOMPurify from 'dompurify'
window.__run = function() {
  const SRC = '<svg viewBox="0 0 200 150" xmlns="http://www.w3.org/2000/svg" width="60mm" height="45mm"><circle cx="100" cy="75" r="35" stroke="black" fill="none"/></svg>';
  const TAGS=['svg','circle','p'];
  const ATTRS=['viewBox','xmlns','width','height','cx','cy','r','stroke','fill'];
  const cases = {
    'A: ALLOWED_TAGS+ALLOWED_ATTR only': { ALLOWED_TAGS:TAGS, ALLOWED_ATTR:ATTRS },
    'B: + USE_PROFILES(html,svg)':       { ALLOWED_TAGS:TAGS, ALLOWED_ATTR:ATTRS, USE_PROFILES:{html:true,svg:true} },
    'C: FORBID_ATTR only':               { FORBID_ATTR:['href','xlink:href'], FORBID_TAGS:['script'], ADD_TAGS:['svg'], ...{} },
  };
  const out = {};
  for (const [k,opt] of Object.entries(cases)) {
    try { out[k] = DOMPurify.sanitize(SRC, opt); } catch(e) { out[k] = 'ERR '+e.message; }
  }
  // D: 默认 + USE_PROFILES
  out['D: USE_PROFILES only'] = DOMPurify.sanitize(SRC, { USE_PROFILES:{html:true,svg:true} });
  return out;
}
