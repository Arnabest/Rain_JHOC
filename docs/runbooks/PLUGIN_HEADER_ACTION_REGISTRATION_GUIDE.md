# 插件快捷栏图标注册与图层分离开发指南 (Plugin Header Action Registration Guide)

> **适用范围**：所有向会话栏上方快捷栏（HeaderActionSlot）注册快捷图标、自定义浮动面板或右键菜单的插件与核心功能模块。  
> **核心原则**：**图层物理分离 (Layer Decoupling)** 与 **视口自适应避让 (Viewport-Fitted Positioning)**。

---

## 1. 架构背景与图层受困痛点

会话栏上方快捷栏（`HeaderActionSlot`）具有以下容器特性：
1. **横向滚动与溢出裁剪**：为了在图标较多时自适应排布，外层容器设置了 `overflow-x-auto` 与父级的 `overflow-hidden`。
2. **复合层叠上下文**：Header 顶栏具有 `backdrop-blur-md`（背景毛玻璃）与 `z-30` 层级。在现代浏览器 CSS 规范中，`backdrop-filter` 会迫使其子元素的所有 `position: fixed` 和 `position: absolute` 将该包含块作为定位基准，无法真正浮动至整个视口顶层。

### 历史问题与反思
此前若插件直接在自身容器内编写 `position: absolute` 或普通 `position: fixed` 的下拉面板/右键菜单，或者随意使用 `e.stopPropagation()` 强行拦截右键事件，会导致以下致命问题：
- 下拉或右键菜单被快捷栏边框截断、无法完整展开；
- 缩放比例变动时坐标错位；
- 右键点击图标没有任何反应，破坏一致性体验。

**TTS 播报图标 (VoiceBroadcastButton) 是系统钦定的参考标杆**：其右键音量菜单通过 `<ScaledPortal>` 挂载到全局顶层 DOM 节点，并由 `calculateFittedFloatingPosition` 计算坐标，彻底实现与快捷栏图层物理分离。

---

## 2. 插件注册两套标准路径

### 路径 A：标准快捷图标模式 (强烈推荐，满足 95% 场景)

对于绝大多数工具与快捷触发型插件，只需使用标准参数注册，**系统会自动提供顶层分离的右键管理菜单**，插件作者无需编写一行右键或浮层代码！

#### 注册代码示例
```typescript
// 插件 onMount 生命周期内：
context.ui.registerHeaderAction({
  id: 'my-plugin-action',
  label: '代码分析',
  title: '启动全项目代码静态分析 (Ctrl+Shift+A)',
  icon: 'code',             // 支持系统内置图标字符串或 React 元素
  variant: 'pill',          // 可选: 'icon' | 'pill' | 'badge' | 'button'
  badge: 'PRO',             // 可选: 徽标角标文本或数字
  badgeColor: 'bg-indigo-500',
  order: 45,                // 建议排布权重 (10~90)
  onClick: (e) => {
    // 左键点击触发业务逻辑
    context.ui.notify('正在启动代码分析引擎...');
  },
});
```

#### 系统自动托管特性：
- **图层物理分离**：用户右键该图标时，系统自动在顶层 Portal（`<ScaledPortal>`）中弹出专属右键菜单，`zIndex={10000}`，绝对不会被快捷栏父级容器裁剪；
- **自适应避让**：右键菜单自动贴合图标下方，在屏幕右侧或下边缘时自动计算视口避让；
- **开箱即用管理能力**：自动包含“立即触发/打开”、“从快捷栏隐藏”、“向前移”、“向后移”以及“展示区排布管理”。

---

### 路径 B：自定义专属浮动面板模式 (高级场景，对齐 TTS 播报标杆)

若插件需要实现像 TTS 播报图标一样的复杂交互（如右键呼出专属的参数滑块调节面板，或左键呼出多模态感知调控面板），必须严格遵守以下**三项物理铁律**：

#### 铁律 1：绝不使用内嵌 Absolute / Fixed
- **禁止**：直接在组件内渲染 `<div className="absolute top-full right-0 ...">`；
- **必须**：引入 `<ScaledPortal>` 挂载到全局顶层容器（`zIndex` 标定为 `10000`）。

#### 铁律 2：坐标计算必须使用 calculateFittedFloatingPosition
- **禁止**：直接拿 `e.clientX` / `e.clientY` 裸写 style；
- **必须**：通过 `targetElement.getBoundingClientRect()` 结合 `calculateFittedFloatingPosition` 换算逻辑坐标并自动进行视口边界避让保护。

#### 铁律 3：必须具备完整平滑关闭监听
- 必须监听 `mousedown`（外部点击）、`Escape` 键以及窗口 `resize` 事件以自动关闭浮层。

---

## 3. 常见反模式与避坑清单 (Do's & Don'ts)

| 场景 | 错误反模式 (Don't) | 正确规范 (Do) |
|---|---|---|
| **浮层挂载位置** | 在图标内部直接写 `absolute top-full` 或 `fixed` | 必须使用 `<ScaledPortal>` 挂载至顶层节点 |
| **右键事件处理** | 使用 `onContextMenu={(e) => e.stopPropagation()}` 吞没事件却不弹菜单 | 允许事件冒泡由系统托管，或在专属处理中弹出 `<ScaledPortal>` 菜单 |
| **菜单坐标计算** | 直接使用 `top: 100%` 或硬编码屏幕像素坐标 | 使用 `calculateFittedFloatingPosition` 自动换算与边界避让 |
| **浮层关闭机制** | 只依赖按钮自身点击 Toggle，缺少全局事件监听 | 同时监听 `mousedown` 外部点击、`Escape` 按键与 `resize` 缩放 |
| **z-index 标定** | 随意写 `z-50` 或 `z-99` | 顶层浮动菜单统一标定为 `zIndex={10000}` |

---

## 4. 插件审核与自测检查项 (Checklist)

所有新增或重构的快捷栏插件在合并前必须通过以下检查：
- [ ] **检查项 1**：在主窗口缩放比例为 80%、100%、125%、150% 时，右键呼出菜单坐标无偏移。
- [ ] **检查项 2**：在靠近屏幕右侧或下边缘点击时，菜单自动向上或向左展开，无任何截断溢出。
- [ ] **检查项 3**：点击外部空白区域或按下 ESC 键，菜单平滑顺畅关闭。
- [ ] **检查项 4**：控制台无任何 React Key 重复警告，无未捕获的事件冒泡异常。
- [ ] **检查项 5**：通过 `npx vitest run tests/test_header_action_context_menu_layer.test.ts` 自动化测试。
