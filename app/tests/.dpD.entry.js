
import DOMPurify from 'dompurify'
window.__fix = function() {
  const SRC = '<svg viewBox="0 0 200 150" xmlns="http://www.w3.org/2000/svg" width="60.0mm" height="45.0mm"><circle cx="100" cy="75" r="35" stroke="black" fill="none"/></svg><img src="data:image/png;base64,iVBORw0KGgo=">';
  const TAGS = ['p','svg','circle','img'];
  const ATTRS = ['viewBox','viewbox','xmlns','width','height','cx','cy','r','fill','stroke','src'];
  const base = { ALLOWED_TAGS: TAGS, ALLOWED_ATTR: ATTRS, FORBID_ATTR:['href','xlink:href','srcset'],
                 USE_PROFILES:{html:true,svg:true,svgFilters:false,mathMl:false} };
  const R = /^data:image\/(png|jpeg|jpg|gif|webp|svg\+xml);base64,[A-Za-z0-9+/=\s]+$/i;
  return {
    // 修复方案1：用 hook 代替 ALLOWED_URI_REGEXP
    'fix1_hook': (function(){
      const prev = DOMPurify.hooks ? null : null;
      DOMPurify.addHook('uponSanitizeAttribute', (node, data) => {
        if (data.attrName === 'src' && !R.test(String(data.attrValue||'').trim())) {
          data.keepAttr = false;
        }
      });
      const out = DOMPurify.sanitize(SRC, base);
      DOMPurify.removeAllHooks();
      return out;
    })(),
    // 修复方案2：ALLOWED_URI_REGEXP 改为"只匹配 data:image 或 任意非 URI 值"
    'fix2_regex': DOMPurify.sanitize(SRC, { ...base,
      ALLOWED_URI_REGEXP: /^(?:data:image\/(?:png|jpeg|jpg|gif|webp|svg\+xml);base64,[A-Za-z0-9+/=\s]+)$/i }),
  };
}
