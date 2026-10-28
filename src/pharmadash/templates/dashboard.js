/* PharmaDash dashboard renderer. Vanilla JS, hand-built SVG, no libraries.
   Reads window.__DASH__ (written by the builder). Bar heights come from numbers the builder parsed out of the labels,
   so a label and its bar can never disagree. */
(function(){
  const D=window.__DASH__;
  const NS="http://www.w3.org/2000/svg";
  const el=(n,a,p)=>{const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);if(p)p.appendChild(e);return e;};
  const reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(!reduce){const st=document.createElement('style');
    st.textContent='@keyframes grow{to{transform:scaleY(1)}}@keyframes growx{to{transform:scaleX(1)}}@keyframes fade{to{opacity:1}}';
    document.head.appendChild(st);}
  const MONO='IBM Plex Mono, monospace', HEAD='Space Grotesk, sans-serif';
  const DARK={grid:'#1E2935',axis:'#6F7E90',cat:'#AEBED0',lab:D.accentLight,sub:'#8FA0B2',inbar:'#fff',ref:'#5A6B7D'};
  const LIGHT={grid:'#E4E8ED',axis:'#9AA6B4',cat:'#5C6775',lab:D.accent,sub:'#8A95A3',inbar:'#fff',ref:'#9AA6B4'};

  function scale(maxv){
    const raw=Math.max(maxv,1e-9)/4, mag=Math.pow(10,Math.floor(Math.log10(raw)));
    const step=[1,2,2.5,5,10].find(s=>s*mag>=raw)*mag;
    return {step:step, ymax:Math.ceil(maxv*1.14/step)*step};
  }
  const num=v=>Number.isInteger(v)?String(v):String(+v.toFixed(2));
  const tick=(c,v)=>(c.prefix||'')+num(v)+(c.suffix||'');
  const anim=(dir,cx,cy,delay)=>reduce?'':'transform-origin:'+cx+'px '+cy+'px;transform:scale'+dir+'(0);animation:grow'+(dir==='X'?'x':'')+' .8s '+delay+'s forwards cubic-bezier(.2,.7,.2,1)';

  function defsFor(svg,id){
    const defs=el('defs',{},svg);
    const pat=el('pattern',{id:'hatch-'+id,width:7,height:7,patternUnits:'userSpaceOnUse',patternTransform:'rotate(45)'},defs);
    el('rect',{width:7,height:7,fill:'rgba('+D.accentRgb+',.14)'},pat);
    el('line',{x1:0,y1:0,x2:0,y2:7,stroke:D.accent,'stroke-opacity':.75,'stroke-width':3},pat);
    return 'url(#hatch-'+id+')';
  }
  function fillFor(p,hatch){
    if(p.style==='projected')return {fill:hatch,stroke:D.accent,'stroke-width':1.5,'stroke-dasharray':'none'};
    if(p.style==='approx')return {fill:D.accent,'fill-opacity':.62,stroke:D.accentLight,'stroke-width':1.4,'stroke-dasharray':'4 3'};
    return {fill:p.highlight?D.gold:D.accent,stroke:'none'};
  }
  const T=(svg,a,txt)=>{el('text',a,svg).textContent=txt;};

  /* ---- vertical bars ---- */
  function vbars(svg,c,o,th){
    const W=o.W,H=o.H,mL=o.mL,mR=o.mR,mT=o.mT,mB=o.mB, iW=W-mL-mR, iH=H-mT-mB;
    const vals=c.points.map(p=>p.value).concat(c.ref?[c.ref.value]:[]);
    const sc=scale(Math.max.apply(null,vals));
    const yv=v=>mT+(1-v/sc.ymax)*iH, y0=yv(0);
    for(let g=0;g<=sc.ymax+1e-9;g+=sc.step){
      el('line',{x1:mL,y1:yv(g),x2:mL+iW,y2:yv(g),stroke:th.grid,'stroke-width':1},svg);
      T(svg,{x:mL-8,y:yv(g)+4,'text-anchor':'end',fill:th.axis,'font-size':o.fs-1,'font-family':MONO},tick(c,g));
    }
    const hatch=defsFor(svg,svg.id), n=c.points.length, slot=iW/n, bw=Math.min(o.maxBar,slot*.56);
    c.points.forEach((p,i)=>{
      const cx=mL+slot*i+slot/2, x=cx-bw/2, top=yv(p.value);
      if(p.style==='nd'){
        el('rect',{x:x,y:y0-22,width:bw,height:22,rx:4,fill:'none',stroke:th.axis,'stroke-width':1.2,'stroke-dasharray':'4 3'},svg);
        T(svg,{x:cx,y:y0-28,'text-anchor':'middle',fill:th.sub,'font-size':o.fs,'font-family':MONO},'n/d');
      }else{
        const f=fillFor(p,hatch);
        el('rect',Object.assign({x:x,y:top,width:bw,height:Math.max(y0-top,1),rx:4,style:anim('Y',cx,y0,i*.1)},f),svg);
        if(p.style==='projected'&&p.booked!=null){
          el('rect',{x:x,y:yv(p.booked),width:bw,height:y0-yv(p.booked),rx:4,fill:D.accent,style:anim('Y',cx,y0,i*.1+.05)},svg);
          T(svg,{x:cx,y:yv(p.booked)+16,'text-anchor':'middle',fill:th.inbar,'font-size':o.fs,'font-weight':600,'font-family':MONO},p.bookedText);
        }
        T(svg,{x:cx,y:top-(p.style==='projected'?o.fs+9:9),'text-anchor':'middle',fill:p.style==='approx'?th.sub:(p.highlight?D.gold:th.lab),
          'font-family':HEAD,'font-weight':700,'font-size':o.vfs},p.text);
        if(p.style==='projected')T(svg,{x:cx,y:top-7,'text-anchor':'middle',fill:th.sub,'font-size':o.fs-1,'font-family':MONO},'projected');
      }
      T(svg,{x:cx,y:H-mB+o.fs+11,'text-anchor':'middle',fill:th.cat,'font-size':o.fs+1,'font-weight':600,'font-family':HEAD},p.label);
    });
    if(c.ref){
      const ry=yv(c.ref.value);
      el('line',{x1:mL,y1:ry,x2:mL+iW,y2:ry,stroke:th.ref,'stroke-width':1.2,'stroke-dasharray':'5 4'},svg);
      T(svg,{x:mL+iW+6,y:ry+4,fill:th.sub,'font-size':o.fs-1,'font-family':MONO},c.ref.label);
    }
  }

  /* ---- horizontal bars ---- */
  function hbars(svg,c,o,th){
    const W=o.W,mL=o.mL,mR=o.mR,row=o.row, H=o.mT+c.points.length*row+10;
    svg.setAttribute('viewBox','0 0 '+W+' '+H);
    const iW=W-mL-mR, sc=scale(Math.max.apply(null,c.points.map(p=>p.value)));
    const hatch=defsFor(svg,svg.id);
    for(let g=0;g<=sc.ymax+1e-9;g+=sc.step){
      const x=mL+g/sc.ymax*iW;
      el('line',{x1:x,y1:o.mT-6,x2:x,y2:H-8,stroke:th.grid,'stroke-width':1},svg);
      T(svg,{x:x,y:o.mT-12,'text-anchor':'middle',fill:th.axis,'font-size':o.fs-1,'font-family':MONO},tick(c,g));
    }
    c.points.forEach((p,i)=>{
      const cy=o.mT+row*i+row/2, h=Math.min(26,row*.56), w=Math.max(p.value/sc.ymax*iW,2);
      T(svg,{x:mL-10,y:cy+4,'text-anchor':'end',fill:th.cat,'font-size':o.fs+1,'font-weight':600,'font-family':HEAD},p.label);
      if(p.style==='nd'){T(svg,{x:mL+8,y:cy+4,fill:th.sub,'font-size':o.fs,'font-family':MONO},'n/d');return;}
      el('rect',Object.assign({x:mL,y:cy-h/2,width:w,height:h,rx:4,style:anim('X',mL,cy,i*.08)},fillFor(p,hatch)),svg);
      T(svg,{x:mL+w+8,y:cy+5,fill:p.highlight?D.gold:th.lab,'font-family':HEAD,'font-weight':700,'font-size':o.vfs},p.text);
    });
  }

  /* ---- line ---- */
  function lines(svg,c,o,th){
    const W=o.W,H=o.H,mL=o.mL,mR=o.mR,mT=o.mT,mB=o.mB, iW=W-mL-mR, iH=H-mT-mB;
    const sc=scale(Math.max.apply(null,c.points.map(p=>p.value))), yv=v=>mT+(1-v/sc.ymax)*iH, n=c.points.length;
    const xs=i=>mL+(n===1?iW/2:iW*i/(n-1));
    for(let g=0;g<=sc.ymax+1e-9;g+=sc.step){
      el('line',{x1:mL,y1:yv(g),x2:mL+iW,y2:yv(g),stroke:th.grid,'stroke-width':1},svg);
      T(svg,{x:mL-8,y:yv(g)+4,'text-anchor':'end',fill:th.axis,'font-size':o.fs-1,'font-family':MONO},tick(c,g));
    }
    const real=c.points.map((p,i)=>({p:p,i:i})).filter(q=>q.p.style!=='nd');
    const pts=real.map(q=>xs(q.i)+','+yv(q.p.value)).join(' ');
    const g=el('g',{style:reduce?'':'opacity:0;animation:fade .9s .1s forwards'},svg);
    el('polygon',{points:xs(real[0].i)+','+yv(0)+' '+pts+' '+xs(real[real.length-1].i)+','+yv(0),fill:'rgba('+D.accentRgb+',.14)'},g);
    el('polyline',{points:pts,fill:'none',stroke:D.accent,'stroke-width':3,'stroke-linejoin':'round','stroke-linecap':'round'},g);
    real.forEach(q=>{
      const proj=q.p.style==='projected';
      el('circle',{cx:xs(q.i),cy:yv(q.p.value),r:5,fill:proj?'none':D.accent,stroke:proj?D.accent:th.grid==='#1E2935'?'#0E141B':'#fff','stroke-width':2,'stroke-dasharray':proj?'3 2':'none'},g);
      T(g,{x:xs(q.i),y:yv(q.p.value)-12,'text-anchor':'middle',fill:q.p.style==='approx'?th.sub:th.lab,'font-family':HEAD,'font-weight':700,'font-size':o.vfs},q.p.text);
    });
    c.points.forEach((p,i)=>T(svg,{x:xs(i),y:H-mB+o.fs+11,'text-anchor':'middle',fill:th.cat,'font-size':o.fs+1,'font-weight':600,'font-family':HEAD},p.label));
  }

  function draw(id,c,o,th){
    const svg=document.getElementById(id); if(!svg||!c)return;
    ({bar:vbars,hbar:hbars,line:lines})[c.kind](svg,c,o,th);
  }
  const horiz=c=>c&&c.kind==='hbar';
  draw('chart',D.chart,{W:920,H:430,mL:horiz(D.chart)?200:62,mR:horiz(D.chart)?110:(D.chart.ref?120:34),mT:40,mB:52,fs:12,vfs:17,maxBar:96,row:54},DARK);
  if(D.mini)draw('mini',D.mini,{W:360,H:200,mL:horiz(D.mini)?110:44,mR:horiz(D.mini)?60:14,mT:26,mB:34,fs:10,vfs:14,maxBar:70,row:36},LIGHT);
})();
