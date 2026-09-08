# 07 - UI 插件扩展、派生选择器突变与插槽故障隔离错题集 (UI Extensibility, Selector Mutation & Slot Fault Isolation Lessons)

> 本目录归纳自 Verse Agent 桌面客户端顶栏自定义功能图标展示区开发实战中，关于状态派生选择器引用突变引发 React 死循环、单块代码编辑截断接口导出、以及插件动态扩展插槽未实施故障原地吸收的核心教训，作为后续 UI 架构与插件体系的终身免疫规约。

---

## 1. LESSON #404: Zustand 派生选择器返回新引用引发 React 19 级联重渲染死循环

### 1.1 事故症状
- 在开发顶栏自定义功能图标展示区组件 (`HeaderActionSlot.tsx`) 时，为便捷获取已排序的动作列表，在组件内直接编写：
  ```tsx
  const actions = useHeaderActionStore((state) => state.getSortedActions());
  ```
- 桌面客户端窗口立即抛出致命错误，被外层 `ErrorBoundary` 拦截，报错信息为：
  `Maximum update depth exceeded. This can happen when a component repeatedly calls setState inside componentWillUpdate or componentDidUpdate. React limits the number of renders to prevent an infinite loop.`
- 客户端主窗口红框报错，工作区无法正常交互。

### 1.2 根因深度剖析
1. **Zustand v5 / React 19 `useSyncExternalStore` 判定机制**：
   - React 18/19 采用 `useSyncExternalStoreWithSelector` 来订阅外部状态源；
   - 订阅者会通过 `Object.is(prevSelection, nextSelection)` 比对选择器在两次快照中的计算结果；
2. **`getSortedActions` 每次调用生成全新数组对象引用**：
   - `getSortedActions` 内部通过 `Object.values(get().actions).sort(...)` 生成排序列表；
   - 即使底层 `actions` 字典毫厘未动，每次执行 `getSortedActions()` 依然开辟全新的堆内存数组对象；
3. **无限递归更新风暴**：
   - 渲染触发选择器 -> 产生新数组引用 A -> React 检测到选择结果不相等 -> 判定 Store 发生变更并立即安排下一次渲染；
   - 极短时间内循环触发 50+ 次重渲染，直接打爆 React 最大更新深度防护网，导致主应用崩溃。

### 1.3 终身防御规约
1. **选择器引用幂等铁律**：
   - 严禁在 Zustand 选择器中直接执行返回新对象、新数组的无缓存函数（如 `getSortedX()`, `filter()`, `map()`）；
   - 选择器必须直接返回 Store 内部已有的基元值或稳定字典引用：
     ```tsx
     // [PASS] 正确姿势：订阅稳定的状态引用
     const actionsMap = useHeaderActionStore((state) => state.actions);
     ```
2. **计算与排序下沉至组件内 `useMemo`**：
     ```tsx
     // [PASS] 在组件生命周期内基于稳定依赖做记忆化派生
     const actions = React.useMemo(() => {
       if (!actionsMap) return [];
       return Object.values(actionsMap).sort((a, b) => (a.order ?? 100) - (b.order ?? 100));
     }, [actionsMap]);
     ```
   - 仅在 `actionsMap` 字典因增删改发生物理变更时才重新排序，平时重渲染耗时为 0 且引用绝对恒定。

---

## 2. LESSON #405: 单块文本替换截断类型定义引发 HMR 编译雪崩

### 2.1 事故症状
- 在微调 `headerActionStore.ts` 内部常量时，单块文本替换起始行号范围指定过大，导致前置导出的核心接口（`export interface HeaderActionItem`, `HeaderActionState`）被误擦除；
- Vite 开发服务器监听到文件修改后触发热重载 (HMR)，编译失败并向前端客户端推送 Syntax/Type Error，导致窗口崩溃。

### 2.2 根因剖析
- 追求快速替换，未严格审查 TargetContent 的闭合边界与起始行号，破坏了文件的静态语义契约（AST Broken）。

### 2.3 终身防御规约
1. **范围精确定位原则**：
   - 执行 `replace_file_content` 时，必须确保 StartLine/EndLine 与 TargetContent 高度收敛至待改代码块自身，严禁跨越不相干的 `interface` 或 `type` 导出区；
2. **编辑后强制编译验证**：
   - 修改任何 TypeScript 核心 Store 或组件后，严禁口头声明成功，必须单机执行 `npm run build` (`tsc -b && vite build`) 验证通过。

---

## 3. LESSON #406: 动态插件插槽缺乏局部故障隔离引发单点冒泡穿透 (Slot Fault Containment)

### 3.1 事故症状
- 插件插槽用于渲染来自外部业务插件的自定义按钮、图标、胶囊或自定义 `render()`；
- 一旦某一个插件传入非法 props、未解析的图标名、或自定义渲染抛出异常，会导致整条顶栏甚至整个应用树挂掉。

### 3.2 终身防御规约
1. **插槽级局部 Fail-Safe 守卫 (`ActionSlotBoundary`)**：
   - 任何可被外部插件注入的动态插槽容器（如 `HeaderActionSlot`），外层必须包裹局部 `ErrorBoundary`；
   - 当插件自定义渲染抛出未捕获异常时，由插槽自身原地降级吸收并打印警告，严禁将异常冒泡至 `HeaderBar` 或根 `App`；
2. **图标解析绝对防崩**：
   - `resolveIcon` 统一加装 `try...catch` 兜底，当传入非法图标名或畸形 ReactNode 时自动回退至默认安全的 `Sparkles` 图标，保证 UI 恒定可渲染。
