# 08 - 客户端存储水合、GPU 纹理耗尽与输入法管道阻塞错题集 (Client Storage Hydration, GPU Texture Exhaustion & IME Pipeline Lessons)

> 本目录归纳自 `infinite-canvas` 图片生成工作台 (`web/src/pages/image/index.tsx`) 真实排障与性能重构实战中，关于前端 IndexedDB 大文件急切水合打爆 GPU 显存、F5/重启无法自愈、以及 React 顶层状态受控输入阻断系统输入法 (IME/TSF) 消息循环的核心教训，作为后续富媒体工作台与复杂单页应用架构的终身免疫规约。

---

## 1. LESSON #407: 客户端累积大文件启动急切水合导致 GPU 纹理显存耗尽与 F5 自愈失效陷阱

### 1.1 事故症状
- 在图片生成工作台运行多轮后，整个网页发生极其严重的卡顿；
- **反常现象 1**：用户尝试按 F5 刷新甚至完全关闭浏览器重启，卡顿完全没有缓解，进入页面后依然卡顿；
- **反常现象 2**：浏览器窗口外部（操作系统其他软件、桌面）运行完全流畅，仅浏览器该标签页出现严重掉帧、CPU/GPU 占用过高。

### 1.2 根因深度剖析
1. **客户端持久化数据的“永生陷阱”**：
   - 用户多轮生成后，在 IndexedDB（`image_files` 库）中留存了 42 张图片 Blob，物理体积累计 370.8 MB；
   - 原代码在页面初始加载 `useEffect` 中直接调用 `readStoredLogs()` -> `Promise.all(values.map(normalizeLog))`；
   - `normalizeLog` 对全部 42 条历史记录强行执行 `resolveImageUrl`，将这 42 张全分辨率大图全部读入内存并生成 `blob:http://...` 永久 Object URL；
2. **GPU 显存/纹理管线爆炸 (Texture Memory Exhaustion)**：
   - 侧边栏历史记录列表直接渲染所有历史卡片，并在卡片中直接渲染这些 Object URL（仅用 CSS 样式 `size-8` 缩减为 32x32px 显示）；
   - Chromium 的 Skia 渲染引擎与 GPU 进程为了绘制这些节点，必须将每张 1024px~2048px 的压缩 PNG/JPEG 解码为未压缩的 32 位 RGBA 像素阵列；
   - 单张未压缩纹理占用 4MB~16MB，42 张图片瞬间吃掉 **800MB~1.5GB 物理显存与 GPU 纹理缓存**；
   - Chromium Compositor 线程和渲染主线程因显存交换与纹理频繁失效而发生严重抖动；
3. **为什么 F5 / 重启浏览器完全无效**：
   - React 状态随刷新销毁，但 IndexedDB 是硬盘物理持久化存储；
   - 每次刷新后，启动逻辑立刻在几毫秒内重新拉取全部 370MB Blob 并重新灌满 GPU 显存，导致“刷新无法自愈”。

### 1.3 终身防御规约
1. **元数据与重负载资源按需分离原则 (Metadata-First Hydration)**：
   - 页面初始加载历史列表时，**严禁主动拉取大文件二进制 Blob 或生成 Object URL**；
   - 初始查询只读取纯文本与数值元数据（`id`, `title`, `prompt`, `model`, `time`, `storageKey` 等），加载时间控制在 5ms 内，显存开销为 0；
   - 仅当用户点击某一具体记录进入预览态时，才按需单独解析该记录对应的媒体资源。
2. **微缩图原生硬裁剪原则 (Worker-Thread Micro Thumbnail)**：
   - 严禁用 CSS 缩放全分辨率原图来充当列表缩略图；
   - 若列表必须展示缩略图，必须使用 `window.createImageBitmap(blob, { resizeWidth: 64, resizeHeight: 64, resizeQuality: 'low' })` 在后台工作线程直接以低显存成本解码为 64x64 微缩位图；
   - 通过离屏 Canvas 导出为 1KB 极小 JPEG 数据缓存，立即关闭原始 ImageBitmap 并释放原 Blob；
   - 40 张微缩图总显存开销由 1.5GB 骤降至 640KB（降低 2400 倍）。

---

## 2. LESSON #408: 受控文本输入与多子树 Fiber 渲染强耦合阻断系统输入法 (IME) 消息循环

### 2.1 事故症状
- 在输入框中进行连续文字输入或使用拼音输入法（如微软拼音、搜狗输入法）时，输入过程严重掉帧、候选词弹窗冻结迟滞、甚至按键丢字；
- 浏览器窗口外输入法完全正常。

### 2.2 根因深度剖析
1. **顶层状态驱动全树频繁重渲染**：
   - `prompt` 状态由顶层 500 行容器组件 `ImagePage` 通过 `useState("")` 直接管理；
   - 用户每输入一个拼音字母（如打出 `zhong` 触发 5 次 `onChange`），顶层组件就会同步触发 5 次全局 Fiber 树 Diff 与重渲染；
2. **内联函数与未记忆化依赖泄漏**：
   - 容器内的动作函数（如 `saveResultToAssets`, `downloadImage`, `addResultToReferences`）未通过 `useCallback` 固化，每次按键均生成新引用；
   - 导致包含大图、配置面板、表单的多个重量级子组件（`GenerationSettings`, `ResultImageCard` 等）随每次按键强制重复渲染；
3. **系统级 TSF (Text Services Framework) IPC 消息阻塞**：
   - Windows 原生输入法运行于独立进程，通过 TSF 接口与 Chromium 渲染进程进行 IPC 通信；
   - 当 Chromium 渲染主线程因为高频 React 重渲染与繁重 DOM 计算陷入长任务（Long Tasks > 50ms）时，TSF 的组合键与选词消息被排队阻塞，导致物理层面的输入法卡顿与掉字。

### 2.3 终身防御规约
1. **高频受控输入物理隔离铁律 (Decoupled Input State)**：
   - 将文本输入框抽离为独立的 memoized `PromptSection`，内部自闭环管理受控输入状态；
   - 顶层容器严禁以字符级颗粒度监听高频输入；顶层仅通过 `promptRef` 保持对最新文本的引用，并通过布尔状态（如 `hasPrompt` / `canGenerate`）控制外部按钮的启用/禁用；
   - 用户连续打字 100 字符，顶层容器组件与外部兄弟组件的 React 重渲染次数必须严格控制为 0~1 次；
2. **反向同步采用 Ref 契约**：
   - 外部业务（如历史模板回填、Agent 派发输入、重置表单）通过 `forwardRef` + `useImperativeHandle` 暴露的命令式接口同步更新输入框显示，保持单向数据流与高性能并存；
3. **闭包依赖彻底脱敏**：
   - 子组件操作函数若需读取文本，统一从 `promptRef.current` 中获取，切断因 `[prompt]` 引起的 `useCallback` 引用频繁失效。
