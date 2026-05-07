"""
ProVisionGuard AI — Dashboard Server
=====================================
Run: python dashboard.py
Open: http://localhost:5000
"""

from flask import Flask, render_template_string, Response, jsonify
from flask_socketio import SocketIO, emit
import cv2
import numpy as np
import time
import threading
import base64
import json
import os
from datetime import datetime
from collections import deque

app    = Flask(__name__)
app.config['SECRET_KEY'] = 'provisionguard-secret-2024'
sio    = SocketIO(app, cors_allowed_origins="*",
                  async_mode='threading')

# ── Shared state (from provisionguard.py) ─────────
dashboard_state = {
    'persons'      : {},
    'alert_log'    : deque(maxlen=50),
    'system_start' : time.time(),
    'frame_b64'    : None,
    'fps'          : 0.0,
    'total_alerts' : 0,
    'snapshots'    : [],
}
state_lock = threading.Lock()

def update_dashboard(persons, alerts,
                     frame, fps):
    """Call this from provisionguard.py to push updates."""
    with state_lock:
        dashboard_state['persons'] = persons
        dashboard_state['fps']     = fps
        if frame is not None:
            _, buf = cv2.imencode(
                '.jpg', frame,
                [cv2.IMWRITE_JPEG_QUALITY, 75]
            )
            dashboard_state['frame_b64'] = (
                base64.b64encode(buf).decode('utf-8')
            )
        for a in alerts:
            dashboard_state['alert_log'].appendleft(a)
            dashboard_state['total_alerts'] += 1

# ── HTML Template ─────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProVisionGuard AI</title>
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Share+Tech+Mono&family=Exo+2:wght@300;400;600;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
<style>
/* ── RESET & BASE ───────────────────────────── */
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:        #030610;
  --bg2:       #070d1f;
  --bg3:       #0b1428;
  --panel:     #0d1a2e;
  --panel2:    #0f1e35;
  --border:    rgba(0,180,255,0.12);
  --border2:   rgba(0,180,255,0.25);
  --accent:    #00b4ff;
  --accent2:   #0066ff;
  --gold:      #f0a800;
  --green:     #00ff88;
  --red:       #ff2244;
  --orange:    #ff7700;
  --yellow:    #ffd700;
  --text:      #c8daf0;
  --text2:     #6a8aaa;
  --text3:     #3a5a7a;
  --safe:      #00ff88;
  --watch:     #00e5cc;
  --medium:    #ff8800;
  --high:      #ff3300;
  --critical:  #ff0022;
  --trusted:   #00ff88;
  --font-main: 'Exo 2', sans-serif;
  --font-mono: 'Share Tech Mono', monospace;
  --font-head: 'Rajdhani', sans-serif;
}

html,body{
  height:100%;
  background:var(--bg);
  color:var(--text);
  font-family:var(--font-main);
  overflow:hidden;
}

/* ── SCANLINE EFFECT ────────────────────────── */
body::before{
  content:'';
  position:fixed;
  inset:0;
  background:repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(0,0,0,0.08) 2px,
    rgba(0,0,0,0.08) 4px
  );
  pointer-events:none;
  z-index:9999;
}

/* ── SCROLLBARS ─────────────────────────────── */
::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-track{background:var(--bg2)}
::-webkit-scrollbar-thumb{
  background:var(--accent2);
  border-radius:2px;
}

/* ── LAYOUT ─────────────────────────────────── */
#app{
  display:grid;
  grid-template-rows:56px 1fr;
  grid-template-columns:1fr;
  height:100vh;
}

#topbar{
  grid-row:1;
  background:var(--bg2);
  border-bottom:1px solid var(--border2);
  display:flex;
  align-items:center;
  padding:0 20px;
  gap:20px;
  position:relative;
  z-index:100;
}

#topbar::after{
  content:'';
  position:absolute;
  bottom:0; left:0; right:0;
  height:1px;
  background:linear-gradient(
    90deg,transparent,
    var(--accent),transparent
  );
}

#main{
  grid-row:2;
  display:grid;
  grid-template-columns:320px 1fr 280px;
  gap:0;
  height:calc(100vh - 56px);
  overflow:hidden;
}

/* ── TOPBAR ─────────────────────────────────── */
.logo{
  display:flex;
  align-items:center;
  gap:10px;
}
.logo-icon{
  width:32px;height:32px;
  border:2px solid var(--accent);
  border-radius:6px;
  display:flex;align-items:center;
  justify-content:center;
  position:relative;
  overflow:hidden;
}
.logo-icon::before{
  content:'';
  position:absolute;
  width:16px;height:16px;
  border:2px solid var(--accent);
  border-radius:50%;
  animation:pulse-ring 2s infinite;
}
.logo-icon::after{
  content:'';
  position:absolute;
  width:6px;height:6px;
  background:var(--accent);
  border-radius:50%;
}
@keyframes pulse-ring{
  0%{transform:scale(0.5);opacity:1}
  100%{transform:scale(1.5);opacity:0}
}
.logo-text{
  font-family:var(--font-head);
  font-size:20px;
  font-weight:700;
  letter-spacing:3px;
  color:#fff;
  text-transform:uppercase;
}
.logo-sub{
  font-family:var(--font-mono);
  font-size:9px;
  color:var(--accent);
  letter-spacing:2px;
  margin-top:-4px;
}

.top-stats{
  display:flex;
  gap:24px;
  margin-left:auto;
  align-items:center;
}
.top-stat{
  display:flex;
  flex-direction:column;
  align-items:center;
}
.top-stat-val{
  font-family:var(--font-mono);
  font-size:18px;
  font-weight:700;
  color:var(--accent);
  line-height:1;
}
.top-stat-lbl{
  font-size:9px;
  color:var(--text3);
  letter-spacing:2px;
  text-transform:uppercase;
  margin-top:2px;
}

.status-dot{
  width:8px;height:8px;
  border-radius:50%;
  background:var(--green);
  box-shadow:0 0 8px var(--green);
  animation:blink 1.5s infinite;
}
@keyframes blink{
  0%,100%{opacity:1}
  50%{opacity:0.3}
}

#clock{
  font-family:var(--font-mono);
  font-size:13px;
  color:var(--text2);
  letter-spacing:1px;
}

/* ── LEFT PANEL ─────────────────────────────── */
#left-panel{
  background:var(--bg2);
  border-right:1px solid var(--border);
  display:flex;
  flex-direction:column;
  overflow:hidden;
}

.panel-header{
  padding:12px 16px;
  border-bottom:1px solid var(--border);
  display:flex;
  align-items:center;
  gap:8px;
  background:var(--panel);
}
.panel-title{
  font-family:var(--font-head);
  font-size:13px;
  font-weight:600;
  letter-spacing:3px;
  text-transform:uppercase;
  color:var(--text2);
}
.panel-count{
  margin-left:auto;
  font-family:var(--font-mono);
  font-size:11px;
  color:var(--accent);
  background:rgba(0,180,255,0.1);
  padding:2px 8px;
  border-radius:3px;
  border:1px solid rgba(0,180,255,0.2);
}

#persons-list{
  flex:1;
  overflow-y:auto;
  padding:8px;
  display:flex;
  flex-direction:column;
  gap:8px;
}

.person-card{
  background:var(--panel);
  border:1px solid var(--border);
  border-radius:8px;
  padding:12px;
  position:relative;
  overflow:hidden;
  transition:border-color 0.3s;
  animation:card-in 0.3s ease;
}
@keyframes card-in{
  from{opacity:0;transform:translateX(-10px)}
  to{opacity:1;transform:translateX(0)}
}
.person-card:hover{
  border-color:var(--border2);
}
.person-card::before{
  content:'';
  position:absolute;
  left:0;top:0;bottom:0;
  width:3px;
  background:var(--card-color,var(--accent));
}
.person-header{
  display:flex;
  align-items:center;
  gap:8px;
  margin-bottom:8px;
}
.person-avatar{
  width:32px;height:32px;
  border-radius:6px;
  background:rgba(0,180,255,0.1);
  border:1px solid var(--border2);
  display:flex;align-items:center;
  justify-content:center;
  font-family:var(--font-mono);
  font-size:12px;
  color:var(--accent);
  flex-shrink:0;
}
.person-info{flex:1;min-width:0}
.person-name{
  font-family:var(--font-head);
  font-size:14px;
  font-weight:600;
  color:#fff;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}
.person-cat{
  font-family:var(--font-mono);
  font-size:9px;
  letter-spacing:2px;
  text-transform:uppercase;
  margin-top:1px;
}
.threat-badge{
  font-family:var(--font-mono);
  font-size:9px;
  font-weight:700;
  padding:3px 8px;
  border-radius:3px;
  letter-spacing:2px;
  text-transform:uppercase;
  flex-shrink:0;
}

/* Threat score ring */
.score-ring-wrap{
  display:flex;
  align-items:center;
  gap:10px;
  margin-bottom:8px;
}
.score-ring{
  position:relative;
  width:44px;height:44px;
  flex-shrink:0;
}
.score-ring svg{
  transform:rotate(-90deg);
}
.score-ring-val{
  position:absolute;
  inset:0;
  display:flex;
  align-items:center;
  justify-content:center;
  font-family:var(--font-mono);
  font-size:11px;
  font-weight:700;
  color:#fff;
}
.score-details{flex:1}
.score-detail-row{
  display:flex;
  align-items:center;
  gap:6px;
  margin-bottom:3px;
}
.sdl{
  font-size:9px;
  color:var(--text3);
  letter-spacing:1px;
  width:48px;
  flex-shrink:0;
}
.sdb{
  flex:1;
  height:4px;
  background:rgba(255,255,255,0.05);
  border-radius:2px;
  overflow:hidden;
}
.sdb-fill{
  height:100%;
  border-radius:2px;
  transition:width 0.5s ease;
}
.sdv{
  font-family:var(--font-mono);
  font-size:9px;
  color:var(--text2);
  width:28px;
  text-align:right;
}

.person-behaviors{
  display:flex;
  flex-wrap:wrap;
  gap:4px;
  margin-top:6px;
}
.behavior-tag{
  font-family:var(--font-mono);
  font-size:8px;
  padding:2px 6px;
  border-radius:3px;
  letter-spacing:1px;
  background:rgba(255,120,0,0.15);
  border:1px solid rgba(255,120,0,0.3);
  color:var(--orange);
}

.person-meta{
  display:flex;
  justify-content:space-between;
  margin-top:6px;
  padding-top:6px;
  border-top:1px solid var(--border);
}
.pmeta{
  font-family:var(--font-mono);
  font-size:9px;
  color:var(--text3);
}
.pmeta span{color:var(--text2)}

/* ── CENTER PANEL ───────────────────────────── */
#center-panel{
  display:flex;
  flex-direction:column;
  overflow:hidden;
  background:var(--bg);
}

#feed-wrap{
  flex:1;
  position:relative;
  overflow:hidden;
  background:#000;
  display:flex;
  align-items:center;
  justify-content:center;
}

#feed{
  max-width:100%;
  max-height:100%;
  object-fit:contain;
  display:block;
}

/* Corner HUD decorations */
.corner{
  position:absolute;
  width:20px;height:20px;
  border-color:var(--accent);
  border-style:solid;
  opacity:0.5;
}
.corner-tl{top:10px;left:10px;
  border-width:2px 0 0 2px}
.corner-tr{top:10px;right:10px;
  border-width:2px 2px 0 0}
.corner-bl{bottom:10px;left:10px;
  border-width:0 0 2px 2px}
.corner-br{bottom:10px;right:10px;
  border-width:0 2px 2px 0}

.feed-overlay-tl{
  position:absolute;
  top:14px;left:16px;
  font-family:var(--font-mono);
  font-size:10px;
  color:var(--accent);
  opacity:0.8;
  letter-spacing:2px;
}
.feed-overlay-tr{
  position:absolute;
  top:14px;right:16px;
  font-family:var(--font-mono);
  font-size:10px;
  color:var(--accent);
  opacity:0.8;
  text-align:right;
}
.rec-dot{
  display:inline-block;
  width:6px;height:6px;
  border-radius:50%;
  background:var(--red);
  margin-right:5px;
  box-shadow:0 0 6px var(--red);
  animation:blink 1s infinite;
}

/* No-feed placeholder */
#feed-placeholder{
  text-align:center;
  color:var(--text3);
}
#feed-placeholder .big{
  font-family:var(--font-head);
  font-size:48px;
  letter-spacing:8px;
  color:var(--text3);
  opacity:0.3;
}

#bottom-strip{
  height:52px;
  background:var(--bg2);
  border-top:1px solid var(--border);
  display:grid;
  grid-template-columns:repeat(5,1fr);
  align-items:center;
  padding:0 16px;
  gap:8px;
}
.bstat{
  display:flex;
  flex-direction:column;
  align-items:center;
}
.bstat-val{
  font-family:var(--font-mono);
  font-size:16px;
  font-weight:700;
  line-height:1;
}
.bstat-lbl{
  font-size:8px;
  color:var(--text3);
  letter-spacing:2px;
  text-transform:uppercase;
  margin-top:2px;
}

/* ── RIGHT PANEL ────────────────────────────── */
#right-panel{
  background:var(--bg2);
  border-left:1px solid var(--border);
  display:flex;
  flex-direction:column;
  overflow:hidden;
}

#alert-list{
  flex:1;
  overflow-y:auto;
  padding:8px;
  display:flex;
  flex-direction:column;
  gap:6px;
}

.alert-card{
  background:var(--panel);
  border:1px solid var(--border);
  border-radius:6px;
  padding:10px 12px;
  position:relative;
  overflow:hidden;
  animation:alert-in 0.4s ease;
}
@keyframes alert-in{
  from{opacity:0;transform:translateY(-8px)}
  to{opacity:1;transform:translateY(0)}
}
.alert-card::before{
  content:'';
  position:absolute;
  left:0;top:0;bottom:0;
  width:3px;
  background:var(--alert-color,var(--accent));
}
.alert-header{
  display:flex;
  justify-content:space-between;
  align-items:center;
  margin-bottom:4px;
}
.alert-badge{
  font-family:var(--font-mono);
  font-size:9px;
  font-weight:700;
  letter-spacing:2px;
  padding:2px 6px;
  border-radius:3px;
}
.alert-time{
  font-family:var(--font-mono);
  font-size:9px;
  color:var(--text3);
}
.alert-name{
  font-family:var(--font-head);
  font-size:13px;
  font-weight:600;
  color:#fff;
  margin-bottom:2px;
}
.alert-meta{
  font-family:var(--font-mono);
  font-size:9px;
  color:var(--text3);
  display:flex;
  gap:10px;
}
.alert-behaviors{
  margin-top:5px;
  display:flex;
  flex-wrap:wrap;
  gap:3px;
}
.abeh{
  font-size:8px;
  font-family:var(--font-mono);
  padding:1px 5px;
  background:rgba(255,100,0,0.15);
  border:1px solid rgba(255,100,0,0.25);
  color:var(--orange);
  border-radius:2px;
  letter-spacing:1px;
}

/* ── EMPTY STATES ───────────────────────────── */
.empty-state{
  flex:1;
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:center;
  gap:8px;
  color:var(--text3);
  font-family:var(--font-mono);
  font-size:11px;
  letter-spacing:2px;
  text-transform:uppercase;
}
.empty-icon{
  font-size:28px;
  opacity:0.3;
}

/* ── THREAT COLORS ──────────────────────────── */
.tc-trusted  {color:var(--trusted)}
.tc-safe     {color:var(--safe)}
.tc-watch    {color:var(--watch)}
.tc-medium   {color:var(--medium)}
.tc-high     {color:var(--high)}
.tc-critical {color:var(--critical)}
.tc-blacklist{color:var(--critical)}

.bg-trusted  {background:rgba(0,255,136,0.15);
               border-color:rgba(0,255,136,0.4);
               color:var(--trusted)}
.bg-safe     {background:rgba(0,255,136,0.12);
               border-color:rgba(0,255,136,0.3);
               color:var(--safe)}
.bg-watch    {background:rgba(0,229,204,0.12);
               border-color:rgba(0,229,204,0.3);
               color:var(--watch)}
.bg-medium   {background:rgba(255,136,0,0.15);
               border-color:rgba(255,136,0,0.4);
               color:var(--medium)}
.bg-high     {background:rgba(255,51,0,0.15);
               border-color:rgba(255,51,0,0.4);
               color:var(--high)}
.bg-critical {background:rgba(255,0,34,0.2);
               border-color:rgba(255,0,34,0.5);
               color:var(--critical)}
.bg-blacklist{background:rgba(180,0,20,0.25);
               border-color:rgba(180,0,20,0.6);
               color:var(--critical)}

/* Critical alert flash */
@keyframes critical-flash{
  0%,100%{box-shadow:inset 0 0 0 0 transparent}
  50%{box-shadow:inset 0 0 0 1px var(--critical)}
}
.person-card.critical-active{
  animation:critical-flash 0.8s infinite,
            card-in 0.3s ease;
}

/* ── UPTIME BAR ─────────────────────────────── */
#uptime-bar{
  padding:8px 16px;
  border-top:1px solid var(--border);
  display:flex;
  align-items:center;
  gap:10px;
  font-family:var(--font-mono);
  font-size:9px;
  color:var(--text3);
  letter-spacing:1px;
}
#uptime-bar span{color:var(--accent)}
</style>
</head>
<body>
<div id="app">

  <!-- ── TOP BAR ────────────────────────────── -->
  <div id="topbar">
    <div class="logo">
      <div class="logo-icon"></div>
      <div>
        <div class="logo-text">ProVisionGuard</div>
        <div class="logo-sub">AI SURVEILLANCE SYSTEM v2.0</div>
      </div>
    </div>

    <div class="top-stats">
      <div class="top-stat">
        <div class="top-stat-val" id="t-persons">0</div>
        <div class="top-stat-lbl">Persons</div>
      </div>
      <div class="top-stat">
        <div class="top-stat-val" id="t-threats"
             style="color:var(--red)">0</div>
        <div class="top-stat-lbl">Threats</div>
      </div>
      <div class="top-stat">
        <div class="top-stat-val" id="t-alerts"
             style="color:var(--orange)">0</div>
        <div class="top-stat-lbl">Alerts</div>
      </div>
      <div class="top-stat">
        <div class="top-stat-val" id="t-fps"
             style="color:var(--green)">0</div>
        <div class="top-stat-lbl">FPS</div>
      </div>
    </div>

    <div style="display:flex;align-items:center;
                gap:8px;margin-left:24px">
      <div class="status-dot"></div>
      <span style="font-family:var(--font-mono);
                   font-size:10px;
                   color:var(--green);
                   letter-spacing:2px">LIVE</span>
    </div>

    <div id="clock" style="margin-left:16px"></div>
  </div>

  <!-- ── MAIN ──────────────────────────────── -->
  <div id="main">

    <!-- LEFT: Persons -->
    <div id="left-panel">
      <div class="panel-header">
        <div class="status-dot"
             style="background:var(--accent);
                    box-shadow:0 0 8px var(--accent)">
        </div>
        <div class="panel-title">Active Persons</div>
        <div class="panel-count" id="person-count">0</div>
      </div>
      <div id="persons-list">
        <div class="empty-state" id="persons-empty">
          <div class="empty-icon">👁</div>
          <div>No persons detected</div>
          <div style="font-size:9px;opacity:0.5">
            Waiting for camera feed...
          </div>
        </div>
      </div>
    </div>

    <!-- CENTER: Feed + Stats -->
    <div id="center-panel">
      <div id="feed-wrap">
        <div class="corner corner-tl"></div>
        <div class="corner corner-tr"></div>
        <div class="corner corner-bl"></div>
        <div class="corner corner-br"></div>
        <div class="feed-overlay-tl">
          <span class="rec-dot"></span>
          CAMERA 01 · LIVE
        </div>
        <div class="feed-overlay-tr" id="feed-time">
          --:--:--
        </div>
        <img id="feed" style="display:none">
        <div id="feed-placeholder">
          <div class="big">SIGNAL</div>
          <div style="font-family:var(--font-mono);
                      font-size:11px;
                      letter-spacing:3px;
                      opacity:0.4;
                      margin-top:8px">
            AWAITING FEED...
          </div>
        </div>
      </div>

      <div id="bottom-strip">
        <div class="bstat">
          <div class="bstat-val"
               style="color:var(--accent)"
               id="b-persons">0</div>
          <div class="bstat-lbl">Persons</div>
        </div>
        <div class="bstat">
          <div class="bstat-val"
               style="color:var(--red)"
               id="b-threats">0</div>
          <div class="bstat-lbl">Active Threats</div>
        </div>
        <div class="bstat">
          <div class="bstat-val"
               style="color:var(--orange)"
               id="b-alerts">0</div>
          <div class="bstat-lbl">Total Alerts</div>
        </div>
        <div class="bstat">
          <div class="bstat-val"
               style="color:var(--green)"
               id="b-uptime">00:00</div>
          <div class="bstat-lbl">Uptime</div>
        </div>
        <div class="bstat">
          <div class="bstat-val"
               style="color:var(--yellow)"
               id="b-fps">0</div>
          <div class="bstat-lbl">FPS</div>
        </div>
      </div>
    </div>

    <!-- RIGHT: Alerts -->
    <div id="right-panel">
      <div class="panel-header">
        <div class="status-dot"
             style="background:var(--red);
                    box-shadow:0 0 8px var(--red)">
        </div>
        <div class="panel-title">Alert Feed</div>
        <div class="panel-count"
             id="alert-count"
             style="color:var(--red);
                    border-color:rgba(255,0,34,0.3);
                    background:rgba(255,0,34,0.1)">
          0
        </div>
      </div>
      <div id="alert-list">
        <div class="empty-state" id="alerts-empty">
          <div class="empty-icon">🛡</div>
          <div>No alerts</div>
          <div style="font-size:9px;opacity:0.5">
            System monitoring...
          </div>
        </div>
      </div>
      <div id="uptime-bar">
        <span>SYSTEM</span> ONLINE ·
        <span id="ub-time">--:--:--</span>
      </div>
    </div>

  </div>
</div>

<script>
const socket = io();

// ── Helpers ───────────────────────────────────
function threatClass(label) {
  const m = {
    'TRUSTED':'trusted','SAFE':'safe',
    'WATCH':'watch','MEDIUM':'medium',
    'HIGH':'high','CRITICAL':'critical',
    'BLACKLIST':'blacklist'
  };
  return m[label] || 'safe';
}

function catColor(cat) {
  return {
    'whitelist':'#00ff88',
    'routine':  '#00b4ff',
    'blacklist':'#ff2244',
    'stranger': '#ff8800'
  }[cat] || '#6a8aaa';
}

function sigColor(key) {
  return {
    nervous:'#6496ff',
    looking:'#00c8ff',
    hiding: '#4064ff',
    loiter: '#9650ff',
    sudden: '#0064ff',
    following:'#c850ff',
    emotion:'#0090ff',
  }[key] || '#6a8aaa';
}

function scoreColor(score) {
  if (score >= 0.85) return '#ff0022';
  if (score >= 0.68) return '#ff3300';
  if (score >= 0.48) return '#ff8800';
  if (score >= 0.28) return '#00e5cc';
  return '#00ff88';
}

// SVG ring
function ringPath(score, r=16) {
  const c  = 22;
  const cf = 2 * Math.PI * r;
  const d  = cf * (1 - score);
  const col = scoreColor(score);
  return `
    <svg width="44" height="44"
         viewBox="0 0 44 44">
      <circle cx="${c}" cy="${c}" r="${r}"
        fill="none"
        stroke="rgba(255,255,255,0.05)"
        stroke-width="3"/>
      <circle cx="${c}" cy="${c}" r="${r}"
        fill="none"
        stroke="${col}"
        stroke-width="3"
        stroke-dasharray="${cf}"
        stroke-dashoffset="${d}"
        stroke-linecap="round"/>
    </svg>`;
}

// ── Clock ─────────────────────────────────────
function updateClock() {
  const now = new Date();
  const ts  = now.toLocaleTimeString('en-GB');
  document.getElementById('clock').textContent = ts;
  document.getElementById('feed-time').textContent = ts;
  document.getElementById('ub-time').textContent = ts;
}
setInterval(updateClock, 1000);
updateClock();

// ── Uptime ────────────────────────────────────
let startTime = Date.now();
function updateUptime() {
  const s   = Math.floor((Date.now()-startTime)/1000);
  const m   = Math.floor(s/60);
  const h   = Math.floor(m/60);
  const pad = n => String(n).padStart(2,'0');
  document.getElementById('b-uptime').textContent =
    h > 0
      ? `${pad(h)}:${pad(m%60)}:${pad(s%60)}`
      : `${pad(m)}:${pad(s%60)}`;
}
setInterval(updateUptime, 1000);

// ── State ─────────────────────────────────────
let totalAlerts = 0;
let prevAlertIds = new Set();

// ── Socket events ─────────────────────────────
socket.on('connect', () => {
  console.log('ProVisionGuard connected');
});

socket.on('state_update', (data) => {
  updateFeed(data.frame);
  updatePersons(data.persons);
  updateStats(data.stats);
  if (data.new_alerts) {
    data.new_alerts.forEach(addAlert);
  }
});

// ── Feed ──────────────────────────────────────
function updateFeed(b64) {
  if (!b64) return;
  const feed = document.getElementById('feed');
  const ph   = document.getElementById('feed-placeholder');
  feed.src         = 'data:image/jpeg;base64,' + b64;
  feed.style.display  = 'block';
  ph.style.display    = 'none';
}

// ── Persons ───────────────────────────────────
function updatePersons(persons) {
  const list  = document.getElementById('persons-list');
  const empty = document.getElementById('persons-empty');
  const count = document.getElementById('person-count');
  const ids   = Object.keys(persons);

  count.textContent = ids.length;
  document.getElementById('t-persons').textContent
    = ids.length;
  document.getElementById('b-persons').textContent
    = ids.length;

  // Count threats
  let threats = 0;
  ids.forEach(id => {
    const p = persons[id];
    if (['HIGH','CRITICAL','BLACKLIST']
        .includes(p.threat_label)) threats++;
  });
  document.getElementById('t-threats').textContent
    = threats;
  document.getElementById('b-threats').textContent
    = threats;

  if (ids.length === 0) {
    empty.style.display = 'flex';
    // Remove old cards
    list.querySelectorAll('.person-card')
        .forEach(c => c.remove());
    return;
  }
  empty.style.display = 'none';

  // Update / create cards
  const existingCards = new Set(
    [...list.querySelectorAll('.person-card')]
      .map(c => c.dataset.tid)
  );

  // Remove cards for gone persons
  existingCards.forEach(tid => {
    if (!persons[tid]) {
      const card = list.querySelector(
        `[data-tid="${tid}"]`
      );
      if (card) card.remove();
    }
  });

  ids.forEach(id => {
    const p   = persons[id];
    const tc  = threatClass(p.threat_label);
    const col = scoreColor(p.threat_score);
    let card  = list.querySelector(
      `[data-tid="${id}"]`
    );

    const sigs = p.signals || {};
    const sigKeys = [
      'nervous','looking','hiding',
      'loiter','sudden','following','emotion'
    ];
    const sigLabels = [
      'NERVOUS','LOOKING','HIDING',
      'LOITER','SUDDEN','FOLLOW','EMOTION'
    ];

    const barsHtml = sigKeys.map((k,i) => {
      const v   = (sigs[k] || 0) * 100;
      const sc  = sigColor(k);
      return `
        <div class="score-detail-row">
          <div class="sdl">${sigLabels[i]}</div>
          <div class="sdb">
            <div class="sdb-fill"
                 style="width:${v.toFixed(1)}%;
                        background:${sc}">
            </div>
          </div>
          <div class="sdv">${v.toFixed(0)}</div>
        </div>`;
    }).join('');

    const behs = (p.behaviors||[])
      .map(b =>
        `<span class="behavior-tag">${b}</span>`
      ).join('');

    const dist = p.distance || 99;
    const distTxt = dist < 1.2
      ? `<span style="color:var(--red)">
           ⚠ ${dist.toFixed(1)}m CRITICAL</span>`
      : dist < 2.5
      ? `<span style="color:var(--orange)">
           ! ${dist.toFixed(1)}m ALERT</span>`
      : `<span style="color:var(--safe)">
           ✓ ${dist.toFixed(1)}m</span>`;

    const nameStr = p.name || 'STRANGER';
    const catStr  = (p.category||'stranger')
                    .toUpperCase();
    const catC    = catColor(p.category||'stranger');

    const inner = `
      <div class="person-header">
        <div class="person-avatar">
          ${nameStr.slice(0,2).toUpperCase()}
        </div>
        <div class="person-info">
          <div class="person-name">${nameStr}</div>
          <div class="person-cat"
               style="color:${catC}">
            ${catStr}
          </div>
        </div>
        <div class="threat-badge bg-${tc}">
          ${p.threat_label||'SAFE'}
        </div>
      </div>
      <div class="score-ring-wrap">
        <div class="score-ring">
          ${ringPath(p.threat_score||0)}
          <div class="score-ring-val">
            ${((p.threat_score||0)*100).toFixed(0)}
          </div>
        </div>
        <div class="score-details">
          ${barsHtml}
        </div>
      </div>
      ${behs
        ? `<div class="person-behaviors">${behs}</div>`
        : ''}
      <div class="person-meta">
        <div class="pmeta">
          DIST <span>${distTxt}</span>
        </div>
        <div class="pmeta">
          EMO <span style="color:var(--text)">
            ${p.emotion||'–'}
          </span>
        </div>
        <div class="pmeta">
          ID <span>#${id}</span>
        </div>
      </div>`;

    if (!card) {
      card = document.createElement('div');
      card.className  = 'person-card';
      card.dataset.tid = id;
      list.prepend(card);
    }

    card.innerHTML = inner;
    card.style.setProperty('--card-color', col);

    if (p.threat_label === 'CRITICAL') {
      card.classList.add('critical-active');
    } else {
      card.classList.remove('critical-active');
    }
  });
}

// ── Alerts ────────────────────────────────────
function addAlert(a) {
  totalAlerts++;
  const list  = document.getElementById('alert-list');
  const empty = document.getElementById('alerts-empty');
  const count = document.getElementById('alert-count');

  empty.style.display = 'none';
  count.textContent   = totalAlerts;
  document.getElementById('t-alerts').textContent
    = totalAlerts;
  document.getElementById('b-alerts').textContent
    = totalAlerts;

  const tc   = threatClass(a.label);
  const col  = scoreColor(
    a.score || 0
  );
  const behs = (a.behaviors||[])
    .map(b => `<span class="abeh">${b}</span>`)
    .join('');

  const card = document.createElement('div');
  card.className = 'alert-card';
  card.style.setProperty(
    '--alert-color', col
  );
  card.innerHTML = `
    <div class="alert-header">
      <span class="alert-badge bg-${tc}">
        ${a.label}
      </span>
      <span class="alert-time">${a.time}</span>
    </div>
    <div class="alert-name">
      ${a.name || 'Unknown'}
    </div>
    <div class="alert-meta">
      <span>Score: ${
        ((a.score||0)*100).toFixed(0)}%
      </span>
      <span>${a.emotion||''}</span>
      <span>${
        a.dist ? a.dist.toFixed(1)+'m' : ''
      }</span>
    </div>
    ${behs
      ? `<div class="alert-behaviors">${behs}</div>`
      : ''}`;

  list.prepend(card);

  // Keep max 20 cards
  const cards = list.querySelectorAll('.alert-card');
  if (cards.length > 20) {
    cards[cards.length-1].remove();
  }
}

// ── Stats ─────────────────────────────────────
function updateStats(stats) {
  if (!stats) return;
  if (stats.fps !== undefined) {
    const f = stats.fps.toFixed(1);
    document.getElementById('t-fps').textContent = f;
    document.getElementById('b-fps').textContent  = f;
  }
}
</script>
</body>
</html>"""

# ── Routes ────────────────────────────────────────
@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/health')
def health():
    return jsonify({'status': 'ok',
                    'uptime': time.time() -
                    dashboard_state['system_start']})

# ── Socket ────────────────────────────────────────
@sio.on('connect')
def on_connect():
    print(f"[Dashboard] Client connected")

def broadcast_loop():
    """Push state to all clients every 100ms."""
    last_alert_count = 0
    while True:
        try:
            with state_lock:
                persons_data = {}
                for tid, s in dashboard_state[
                    'persons'
                ].items():
                    persons_data[str(tid)] = s

                frame_b64 = dashboard_state['frame_b64']
                fps       = dashboard_state['fps']
                alerts    = list(
                    dashboard_state['alert_log']
                )

            new_alerts = []
            curr_count = len(alerts)
            if curr_count > last_alert_count:
                diff = curr_count - last_alert_count
                new_alerts = alerts[:diff]
                last_alert_count = curr_count

            sio.emit('state_update', {
                'frame':      frame_b64,
                'persons':    persons_data,
                'new_alerts': new_alerts,
                'stats': {
                    'fps': fps,
                }
            })
        except Exception as e:
            pass
        time.sleep(0.1)

# Start broadcast thread
t = threading.Thread(
    target=broadcast_loop, daemon=True
)
t.start()

if __name__ == '__main__':
    print("\n" + "="*55)
    print("  ProVisionGuard AI — Dashboard")
    print("="*55)
    print("  Open: http://localhost:5000")
    print("  Stop: Ctrl+C")
    print("="*55 + "\n")
    sio.run(app, host='0.0.0.0',
            port=5000, debug=False)