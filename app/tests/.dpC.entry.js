
import DOMPurify from 'dompurify'
window.__bisect = function() {
  const SRC = '<svg viewBox="0 0 200 150" xmlns="http://www.w3.org/2000/svg" width="60.0mm" height="45.0mm"><circle cx="100" cy="75" r="35" stroke="black" fill="none"/></svg>';
  const TAGS = ['p','svg','circle'];
  const ATTRS = ['viewBox','viewbox','xmlns','width','height','cx','cy','r','fill','stroke'];
  const base = { ALLOWED_TAGS: TAGS, ALLOWED_ATTR: ATTRS };
  const variants = {
    'base': {},
    '+ALLOW_DATA_ATTR:false': { ALLOW_DATA_ATTR: false },
    '+ALLOWED_URI_REGEXP': { ALLOWED_URI_REGEXP: /^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=\s]+$/i },
    '+FORBID_TAGS': { FORBID_TAGS: ['foreignObject','use','image','script','style'] },
    '+FORBID_ATTR': { FORBID_ATTR: ['href','xlink:href','srcset'] },
    '+USE_PROFILES': { USE_PROFILES: { html:true, svg:true, svgFilters:false, mathMl:false } },
  };
  const out = {};
  for (const [k,extra] of Object.entries(variants)) {
    out[k] = DOMPurify.sanitize(SRC, { ...base, ...extra });
  }
  return out;
}
