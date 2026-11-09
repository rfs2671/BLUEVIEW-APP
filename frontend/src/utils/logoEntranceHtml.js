import { LOGO_MASK } from './logoMask';

/**
 * The LeveLog login entrance: a swarm of streaking particles pulled into the
 * shape of the logo.
 *
 * Returned as one self-contained HTML page so the SAME animation runs in a
 * react-native-webview on phones and in an iframe on the web. No native module
 * is needed (the app already ships react-native-webview for its PDF viewer), so
 * this can go out over the air.
 *
 * The page draws only the particles. The real logo image and the login card are
 * ordinary React Native views; the page tells the app when to reveal each
 * ('logo', 'ui', 'done') and the app does the fading. That keeps the final
 * screen the actual image, pixel for pixel, with nothing left running.
 *
 * Tuned at "calm" (intensity 0.125) on the prototype dial: about 1.4 seconds,
 * short streaks, no haze.
 *
 *   w, h        size of the overlay in CSS px (the whole screen)
 *   rect        where the logo image is drawn, in overlay px {x, y, w, h}
 *   dark        dark theme (luminous blue-white) or light (ink blue)
 */
export const ENTRANCE_INTENSITY = 0.125;
export const ENTRANCE_SECONDS = 1.35 + 0.4 * ENTRANCE_INTENSITY; // 1.4

export function buildEntranceHtml({ w, h, rect, dark }) {
  const cfg = JSON.stringify({
    w: Math.round(w), h: Math.round(h),
    rx: rect.x, ry: rect.y, rw: rect.w, rh: rect.h,
    dark: !!dark, intensity: ENTRANCE_INTENSITY,
    mask: LOGO_MASK,
  });
  return `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<style>html,body{margin:0;padding:0;background:transparent;overflow:hidden;width:100%;height:100%}canvas{position:absolute;left:0;top:0;width:100%;height:100%;display:block}</style>
</head><body><canvas id="c"></canvas><script>
(function(){
var CFG=${cfg};
function clamp(x,a,b){return x<a?a:(x>b?b:x);}
function sm(a,b,x){var t=clamp((x-a)/(b-a),0,1);return t*t*(3-2*t);}
function eio3(t){return t<.5?4*t*t*t:1-Math.pow(-2*t+2,3)/2;}
function mulberry(a){return function(){a|=0;a=a+0x6D2B79F5|0;var t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}
function post(m){try{if(window.ReactNativeWebView){window.ReactNativeWebView.postMessage(m);}else{parent.postMessage('levelog-entrance:'+m,'*');}}catch(e){}}

var W=CFG.w,H=CFG.h,INT=CFG.intensity,TF=(1.35+0.4*INT)/1.75,DUR=1.75*TF,DT=1/60;
var dpr=Math.min(window.devicePixelRatio||1,2);
var cv=document.getElementById('c');cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);
var ctx=cv.getContext('2d');

// --- the logo's silhouette -> target points
var M=CFG.mask,bin=atob(M.bits),bits=new Uint8Array(bin.length);for(var q=0;q<bin.length;q++)bits[q]=bin.charCodeAt(q);
function on(i,j){if(i<0||j<0||i>=M.w||j>=M.h)return false;var n=j*M.w+i;return (bits[n>>3]>>(7-(n&7)))&1;}
var rnd=mulberry(20261109),pts=[];
for(var j=0;j<M.h;j++)for(var i=0;i<M.w;i++)if(on(i,j))pts.push([i,j]);
for(var a=pts.length-1;a>0;a--){var b=(rnd()*(a+1))|0,t=pts[a];pts[a]=pts[b];pts[b]=t;}
var scaleUp=CFG.rw/196, N=Math.min(9500,Math.max(2200,Math.round(3300*scaleUp*scaleUp)));
N=Math.min(N,pts.length*3);
var tx=new Float32Array(N),ty=new Float32Array(N),x=new Float32Array(N),y=new Float32Array(N),vx=new Float32Array(N),vy=new Float32Array(N),x0=new Float32Array(N),y0=new Float32Array(N),vx0=new Float32Array(N),vy0=new Float32Array(N),dl=new Float32Array(N),kk=new Float32Array(N),ph=new Float32Array(N),cls=new Uint8Array(N);
for(var k=0;k<N;k++){
  var p=pts[k%pts.length];
  tx[k]=CFG.rx+(p[0]+rnd())/M.w*CFG.rw; ty[k]=CFG.ry+(p[1]+rnd())/M.h*CFG.rh;
  x0[k]=(rnd()*1.5-.25)*W; y0[k]=(rnd()*1.3-.15)*H; vx0[k]=(rnd()-.5)*160; vy0[k]=(rnd()-.5)*160;
  dl[k]=rnd()*.32; kk[k]=0.75+rnd()*0.6; ph[k]=rnd()*6.283; cls[k]=(rnd()*4)|0;
}
var groups=[[],[],[],[]];for(var g=0;g<N;g++)groups[cls[g]].push(g);
var THEME=CFG.dark
  ?{op:'lighter',c:['rgba(236,245,255,0.62)','rgba(170,212,248,0.5)','rgba(110,172,228,0.44)','rgba(78,140,208,0.4)']}
  :{op:'multiply',c:['rgba(30,48,62,0.55)','rgba(44,65,83,0.5)','rgba(69,140,181,0.46)','rgba(111,143,166,0.4)']};
var simT=0;
function reset(){x.set(x0);y.set(y0);vx.set(vx0);vy.set(vy0);simT=0;}
function step(){
  var t=simT;
  for(var i=0;i<N;i++){
    var s=clamp((t-dl[i])/0.62,0,1);s=s*s*(3-2*s);
    var px=x[i],py=y[i],pvx=vx[i],pvy=vy[i],k=kk[i]*105;
    var dx=tx[i]-px,dy=ty[i]-py;
    var c=1.4+s*(2*0.62*Math.sqrt(k)-1.0);
    var ax=k*s*dx,ay=k*s*dy;
    var A=420*(0.35+0.65*INT)*(1-s);
    ax+=A*Math.sin(py*0.05+t*2.6+ph[i]);ay+=A*Math.cos(px*0.046-t*2.3+ph[i]*1.3);
    ax-=c*pvx;ay-=c*pvy;
    pvx+=ax*DT;pvy+=ay*DT;px+=pvx*DT;py+=pvy*DT;
    x[i]=px;y[i]=py;vx[i]=pvx;vy[i]=pvy;
  }
  simT+=DT;
}
function draw(T){
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.globalCompositeOperation='source-over';ctx.clearRect(0,0,W,H);
  var dens=0.28+0.72*INT,maxS=9+22*INT,lineA=0.72+0.28*INT;
  var sk=(0.005+0.017*INT)*(1-sm(0.95,1.5,T)),fade=1-sm(1.15,1.58,T);
  if(fade<=0.003)return;
  ctx.globalCompositeOperation=THEME.op;ctx.lineCap='round';ctx.globalAlpha=Math.min(1,fade*lineA);ctx.lineWidth=1.0;
  for(var g2=0;g2<4;g2++){
    var list=groups[g2],lim=Math.ceil(list.length*dens);
    ctx.strokeStyle=THEME.c[g2];ctx.beginPath();
    for(var ii=0;ii<lim;ii++){
      var k2=list[ii],X=x[k2],Y=y[k2],ux=vx[k2]*sk,uy=vy[k2]*sk,L=Math.sqrt(ux*ux+uy*uy);
      if(L>maxS){ux*=maxS/L;uy*=maxS/L;}
      ctx.moveTo(X-ux,Y-uy);ctx.lineTo(X+0.35,Y+0.35);
    }
    ctx.stroke();
  }
  ctx.globalAlpha=1;ctx.globalCompositeOperation='source-over';
}
var t0=null,sent={logo:false,ui:false,done:false},stopped=false;
function frame(now){
  if(stopped)return;
  if(t0===null){t0=now;post('started');}
  var Treal=(now-t0)/1000,T=Treal/TF,n=0;
  while(simT+DT<=T&&n++<20)step();
  draw(T);
  if(!sent.logo&&T>=1.2){sent.logo=true;post('logo');}
  if(!sent.ui&&T>=1.36){sent.ui=true;post('ui');}
  if(T>=1.8){sent.done=true;stopped=true;ctx.clearRect(0,0,W,H);post('done');return;}
  requestAnimationFrame(frame);
}
window.__skip=function(){stopped=true;ctx.clearRect(0,0,W,H);post('done');};
// let layout settle for two frames before starting so the first frame is not a long one
reset();requestAnimationFrame(function(){requestAnimationFrame(frame);});
})();
</script></body></html>`;
}

export default buildEntranceHtml;
