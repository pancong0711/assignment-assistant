
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
window.__step = function() {
  const SRC = '示意图：\n\n<svg viewBox="0 0 200 150" xmlns="http://www.w3.org/2000/svg">\n  <circle cx="100" cy="75" r="35" stroke="black" fill="none"/>\n</svg>';
  const md = new MarkdownIt({html:true, linkify:false, breaks:true});
  const parsed = md.render(SRC);
  const sizes = {
    '1. markdown-it': parsed,
    '2. after normalizeSvgSize': (function(){
      // 复刻 normalizeSvgSize
      return String(parsed).replace(/<svg\b([^>]*)>/gi, (whole, attrs) => {
        if (/\bwidth\s*=/i.test(attrs) && /\bheight\s*=/i.test(attrs)) return whole
        const vb = attrs.match(/\bviewbox\s*=\s*["']\s*[\d.+-]+[\s,]+[\d.+-]+[\s,]+([\d.+-]+)[\s,]+([\d.+-]+)/i)
        if (!vb) return whole
        const w = Number(vb[1]); const h = Number(vb[2])
        if (!(w>0)||!(h>0)) return whole
        const widthMm = Math.min(80, 45*w/h); const heightMm = widthMm*h/w
        return '<svg'+attrs+' width="'+widthMm.toFixed(1)+'mm" height="'+heightMm.toFixed(1)+'mm">'
      })
    })(),
  };
  // 3. 用页面真实配置 sanitize（ALLOWED_TAGS/ATTR 从 richdoc 取不到，这里用完整白名单）
  const TAGS = ['p','br','svg','g','path','line','rect','circle','ellipse','polygon','polyline','text','tspan','defs','marker','title','desc'];
  const ATTRS = ['viewBox','viewbox','xmlns','width','height','cx','cy','r','x','y','x1','y1','x2','y2','d','fill','stroke','stroke-width','points','transform','font-size','id','opacity','class','title'];
  sizes['3. DOMPurify(ALLOWED only)'] = DOMPurify.sanitize(sizes['2. after normalizeSvgSize'],
    { ALLOWED_TAGS: TAGS, ALLOWED_ATTR: ATTRS });
  sizes['4. DOMPurify(+USE_PROFILES+ALLOWED_URI_REGEXP)'] = DOMPurify.sanitize(sizes['2. after normalizeSvgSize'],
    { ALLOWED_TAGS: TAGS, ALLOWED_ATTR: ATTRS, ALLOW_DATA_ATTR:false,
      ALLOWED_URI_REGEXP: /^data:image\/(png|jpeg|jpg|gif|webp|svg\+xml);base64,[A-Za-z0-9+/=\s]+$/i,
      FORBID_TAGS: ['foreignObject','use','image','script','style','iframe','object','embed','form','input'],
      FORBID_ATTR: ['href','xlink:href','srcset'],
      USE_PROFILES: { html:true, svg:true, svgFilters:false, mathMl:false } });
  return sizes;
}
