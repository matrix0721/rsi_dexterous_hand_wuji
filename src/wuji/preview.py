"""Standalone, offline candidate viewer. No CDN or telemetry."""
import json
from pathlib import Path
import numpy as np
from .geometry import points_in


def save_preview(path, observation, plan, hand):
    candidates = []
    for c in plan["candidates"]:
        tips, _, bones, _ = hand.geometry(c["q"])
        t = np.asarray(c["T_base_palm"])
        candidates.append({"tips": points_in(t, tips).tolist(),
                           "bones": points_in(t, bones).tolist(),
                           "palm": t[:3, 3].tolist(),
                           "pregrasp": c["pregrasp_pose"][:3],
                           "score": c["score"], "usable": c["usable"],
                           "metrics": c["geometry_metrics"]})
    all_points = np.vstack([observation.points] +
                           [np.vstack([c["bones"], c["pregrasp"]]) for c in candidates])
    center = (all_points.min(axis=0) + all_points.max(axis=0)) * 0.5
    data = {"cloud": observation.points[::max(1, len(observation.points) // 2000)].tolist(),
            "center": center.tolist(), "candidates": candidates,
            "source": observation.source}
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>v1-wuji · 抓取候选</title><style>
body{margin:0;background:#101b29;color:#dce6ef;font:16px system-ui}main{max-width:1100px;margin:auto;padding:28px}
h1{font-size:26px}canvas{width:100%;height:560px;background:#152333;border-radius:12px;touch-action:none}
select{padding:8px}p{line-height:1.7}pre{white-space:pre-wrap;color:#a9c0d7}</style>
<main><h1>v1-wuji · 接触引导姿态搜索</h1>
<p>拖动旋转，滚轮缩放。灰色：观测点云；蓝色：手部骨架采样；橙色：指腹；绿色：手掌根部；虚线：预抓取至抓取。</p>
<label>候选 <select id="choice"></select></label><p id="meta"></p><canvas id="view"></canvas>
<pre id="metrics"></pre><p>几何预览用于检查姿态，不代表真机碰撞检查或抓取成功。</p></main>
<script>const data=__DATA__;
const canvas=document.querySelector('canvas'),ctx=canvas.getContext('2d'),select=document.querySelector('select');
data.candidates.forEach((c,i)=>{let o=document.createElement('option');o.value=i;o.textContent=`${i+1} · ${c.usable?'可用候选':'待调整'}`;select.append(o)});
let yaw=.5,pitch=.5,zoom=1200,down=null;
function project(p){let x=p[0]-data.center[0],y=p[1]-data.center[1],z=p[2]-data.center[2];
let u=Math.cos(yaw)*x-Math.sin(yaw)*y,v=Math.sin(yaw)*x+Math.cos(yaw)*y;
return [canvas.clientWidth/2+u*zoom,canvas.clientHeight/2-(Math.cos(pitch)*z-Math.sin(pitch)*v)*zoom]}
function dot(p,color,r){let [x,y]=project(p);ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill()}
function draw(){canvas.width=canvas.clientWidth*devicePixelRatio;canvas.height=canvas.clientHeight*devicePixelRatio;
ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);ctx.clearRect(0,0,canvas.width,canvas.height);
// Projection uses CSS pixels while the backing canvas preserves device resolution.
let c=data.candidates[+select.value||0];ctx.save();
data.cloud.forEach(p=>dot(p,'#8b9eaf',1.8));c.bones.forEach(p=>dot(p,'#57b9ff',3));c.tips.forEach(p=>dot(p,'#ffb15b',5));dot(c.palm,'#72e7bb',6);
let a=project(c.pregrasp),b=project(c.palm);ctx.strokeStyle='#72e7bb';ctx.setLineDash([5,5]);ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke();ctx.restore();
document.querySelector('#meta').textContent=`输入：${data.source} · 代价：${c.score.toFixed(4)} · ${c.usable?'通过当前几何筛选':'未通过当前几何筛选'}`;
document.querySelector('#metrics').textContent=JSON.stringify(c.metrics,null,2)}
canvas.onpointerdown=e=>{down=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId)};
canvas.onpointermove=e=>{if(!down)return;yaw+=(e.clientX-down[0])*.01;pitch+=(e.clientY-down[1])*.01;down=[e.clientX,e.clientY];draw()};
canvas.onpointerup=()=>down=null;canvas.onpointercancel=()=>down=null;
canvas.onwheel=e=>{e.preventDefault();zoom*=Math.exp(-e.deltaY*.001);draw()};select.onchange=draw;window.onresize=draw;draw();</script></html>'''
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html.replace("__DATA__", json.dumps(data, allow_nan=False).replace("<", "\\u003c")), encoding="utf-8")
