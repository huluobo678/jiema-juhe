## SPEC UI: 借鉴 sub2api 风格改进接码平台前台/后台界面

### 设计参考
参考 `https://github.com/Wei-Shaw/sub2api` 的 frontend UI 风格（Vue3 + TailwindCSS）：
- 彩色带 icon 背景的统计卡（绿=余额，蓝=项目数，琥珀=今日收码，紫=邀请返利）
- 卡片式项目列表，hover 动效
- 收码流程改用弹窗 overlay，不跳页
- 后台加渠道健康状态面板

### 目标文件

### 1. templates/user/index.html — 前台仪表盘 (重写)
借鉴 sub2api 的 `UserDashboardStats.vue` + `DashboardView.vue` 风格

**统计卡区域** (grid-cols-2 lg:grid-cols-4):
```
[💰 余额 ¥xxx]  [📦 项目数 N]  [⚡ 今日收码 N]  [🎁 返利率 5%]
```
每张卡:
- bg-white, rounded-2xl, shadow-sm, border border-gray-200, p-6
- 左: 44px 圆角 icon 背景 (绿 bg-emerald-100 / 蓝 bg-blue-100 / 琥珀 bg-amber-100 / 紫 bg-purple-100)
- 右: 小字标签(text-gray-500, text-xs) + 大号数值(text-2xl font-bold) + 小字副标签

**卡密兑换卡片**：
- bg-white rounded-2xl shadow-sm border p-6 mb-6
- 标题 "🎫 卡密兑换" font-semibold
- 输入框 + 兑换按钮 一行
- 推荐人Token (选填) 输入框 + 返利提示
- 兑换结果提示区

**项目列表区域**：
```
<div class="project-grid">
  {% for p in projects %}
  <div class="project-card" onclick="openSMSModal({{ p.id }}, '{{ p.name }}')">
    <div class="project-info">
      <span class="project-icon">📦</span>
      <div>
        <div class="project-name">{{ p.name }}</div>
        <div class="project-channel">{{ p.channel_name|default('') }}</div>
      </div>
    </div>
    <div class="price-pill">{{ p.price }} 元</div>
  </div>
  {% endfor %}
</div>
```

项目卡片 CSS:
- bg-white, rounded-xl, border border-gray-200, p-4, cursor-pointer, transition-all 0.2s
- hover: border-emerald-500, translate-x-1, shadow-lg
- 价格: bg-emerald-50 text-emerald-600 font-bold px-4 py-1 rounded-full

**收码弹窗 (代替当前页面切换)**：
当用户点击项目时，弹出半透明遮罩 overlay + 居中白色弹窗，不再隐藏"stepRedeem"

弹窗 HTML 结构:
```html
<div id="smsModalOverlay" style="display:none">
  <div class="modal-overlay" onclick="closeSMSModal()"></div>
  <div class="modal-panel">
    <div class="modal-header">
      <span class="modal-title" id="modalProjectName">项目名</span>
      <span class="balance-badge">💰 <span id="modalBalance">0</span> 元</span>
      <button class="modal-close" onclick="closeSMSModal()">&times;</button>
    </div>
    <div class="modal-body">
      <div class="phone-section">
        <div class="phone-label">当前号码</div>
        <div class="phone-number" id="modalPhone">---</div>
        <div class="countdown">⏱ <span id="modalCountdown">200</span>秒</div>
      </div>
      <div id="modalWaiting" class="waiting-section">
        <div class="spinner"></div>
        <div class="waiting-text">等待验证码中...</div>
        <div class="waiting-hint">自动轮询，收到即止</div>
      </div>
      <div id="modalCode" class="code-section" style="display:none">
        <div class="code-label">验证码</div>
        <div class="code-value" id="modalCodeDisplay">---</div>
        <div class="sms-body" id="modalSMSContent"></div>
      </div>
      <div id="modalTimeout" class="timeout-section" style="display:none">
        <div>⏰ 超时未收到</div>
      </div>
      <div id="modalError" class="error-section" style="display:none"></div>
    </div>
    <div class="modal-footer">
      <button class="btn-outline-danger" id="modalReleaseBtn" onclick="releasePhone()">释放号码</button>
      <button class="btn-outline" onclick="closeSMSModal()">关闭</button>
    </div>
  </div>
</div>
```

CSS 样式:
- `.modal-overlay`: fixed inset-0, bg-black/50, z-40
- `.modal-panel`: fixed inset-0, m-auto, bg-white, rounded-2xl, w-full max-w-md, h-fit, z-50, shadow-2xl, p-0
- `.phone-number`: font-mono, text-3xl, font-bold, color #059669, tracking-widest
- `.code-value`: font-mono, text-5xl, font-extrabold, color #059669, letter-spacing-8px
- `.spinner`: w-10 h-10, border-4 border-gray-200, border-t-emerald-500, rounded-full, animate-spin

**JavaScript 函数** (替换原有 startOrder/pollSMS/releasePhone/backToHome):
保留现有逻辑，但 DOM 操作改为 popup overlay 而非隐藏/显示区域

### 2. templates/admin/dashboard.html — 后台概览 (重写)

保留原有统计卡 + 部署按钮，新增渠道状态面板:

**渠道状态面板**:
```html
<div class="card">
  <h3 style="margin-bottom:16px">🔌 渠道状态</h3>
  <div id="channelStatusPanel">
    <table class="table-modern" style="width:100%">
      <thead>
        <tr>
          <th>渠道</th>
          <th>状态</th>
          <th>熔断器</th>
          <th>并发</th>
          <th>最后健康</th>
        </tr>
      </thead>
      <tbody id="channelStatusBody">
        <tr><td colspan="5" style="text-align:center;color:#94a3b8">加载中...</td></tr>
      </tbody>
    </table>
  </div>
</div>
```

JS:
```js
async function loadChannelStatus() {
  const r = await fetch('/channels/status');
  const d = await r.json();
  if (!d.ok) return;
  const tbody = document.getElementById('channelStatusBody');
  if (!d.channels || d.channels.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#94a3b8">暂无渠道</td></tr>';
    return;
  }
  tbody.innerHTML = d.channels.map(ch => {
    const alive = ch.alive ? '✅ 正常' : '❌ 死亡';
    const cb = ch.circuit === 'closed' ? '✅ 正常' : ch.circuit === 'open' ? '🔴 熔断' : '🟡 半开';
    const color = ch.alive ? (ch.circuit==='closed'?'var(--success)':'var(--warning)') : 'var(--danger)';
    return `<tr>
      <td><strong>${ch.name || ch.id}</strong></td>
      <td style="color:${ch.alive?'var(--success)':'var(--danger)'}">${alive}</td>
      <td style="${ch.circuit==='open'?'color:var(--danger);font-weight:700':'color:var(--success)'}">${cb}</td>
      <td>${ch.concurrent||0}/${ch.concurrent_limit||5}</td>
      <td>${ch.last_ping||'-'}</td>
    </tr>`;
  }).join('');
}
// 每 10 秒刷新
setInterval(loadChannelStatus, 10000);
loadChannelStatus();
```

### 3. static/style.css — 追加 sub2api 风格样式

在文件末尾追加:

```css
/* ========== sub2api 风格卡片 & 弹窗 ========== */
.project-card { ... }
.project-grid { ... }
.modal-overlay { ... }
.modal-panel { ... }
.modal-panel .phone-number { ... }
.modal-panel .code-value { ... }
.modal-panel .spinner { ... }
.modal-panel .modal-header { ... }
.modal-panel .modal-body { ... }
.modal-panel .modal-footer { ... }
.price-pill { ... }
.stat-card-colored { ... }
```

### 实现要求
- 用 inline `<style>` 写在目标模板文件中（便于直接部署），不要引入额外 CSS 文件
- 完全兼容现有后端 routes 和 API 响应格式
- JS 保持与现有 `views/user.py` 的路由一致
- 不修改后端 Python 代码
- 保留现有 sidebar layout 结构（extends user/layout.html）
- 收码弹窗 JS 逻辑复用现有 pollSMS/releasePhone/loadBalance 函数