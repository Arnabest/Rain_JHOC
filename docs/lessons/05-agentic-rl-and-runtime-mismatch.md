# 05 - 强化学习后训练、系统运行时不匹配与记忆漂移错题集 (Agentic RL & Runtime Mismatch Lessons)

> 本目录归纳自 `modern_genai_bilibili` 源码精读与工业级后训练（Post-Training）实战中关于分布式训推断裂、动态重要性采样爆炸、记忆滞后性与底层梯度力学的核心避坑教训，作为 JHOC 全局母体长期免疫规约。

---

## 1. LESSON #361: 训推算子与精度不匹配 (Train-Infer Mismatch) 导致强化学习崩溃 (RL Collapse)
- **症状**：在大规模 Agent 强化学习训练（如 veRL + vLLM/SGLang）中，Actor 权重虽与 Rollout 引擎时刻同步，但几百步后策略熵骤降，模型输出无意义重复字符或 NaN，训练彻底崩溃。
- **根因**：
  1. **底层推理算子与训练算子数值差异**：vLLM 使用 PagedAttention、FlashInfer 和特定 CUDA 汇编加速，可能开启 FP8/INT8 KV Cache；而训练端采用 PyTorch FSDP 标称精度前向传播。二者对同一输入给出的 Logits 存在物理误差（$\pi_{\text{vLLM}} \ne \pi_{\text{PyTorch}}$）；
  2. **重要性采样比率击穿**：若直接将从 vLLM 采集的动作似然视作训练器旧策略 $\pi_{old}$，使得比率 $\frac{\pi_\theta}{\pi_{\text{rollout}}}$ 产生巨大方差，PPO-Clip 的单层截断无法抑制此类算子级系统性偏移。
- **规约**：
  - 强制采用 **Decoupled PPO (解耦校正模式)**；
  - 保持训练端 Actor 在梯度更新前自身前向计算的 $\pi_{old}$ 作为 Trust Region 锚点；
  - 显式引入 Rollout 校正项：
    $$
    w_t = \operatorname{clamp}\left( \frac{\pi_{old}(a_t|s_t)}{\pi_{\text{rollout}}(a_t|s_t)}, 1 - \epsilon, 1 + \epsilon \right)
    $$
  - 生产环境下严禁开启未经数值对齐测试的纯 Bypass 模式。

---

## 2. LESSON #362: 记忆滞后性与物理现实割裂 (Memory Drift & Verify-Before-Act)
- **症状**：Agent 在多轮会话或跨任务工作区中，直接基于记忆库中的历史记录（如“某配置文件在 `/tmp/config.json`”、“某服务运行在端口 8080”）执行破坏性写入或连接，导致写入非法路径或连接死锁。
- **根因**：
  - 盲目相信记忆库的当前有效性。正如 Claude Code 源码 `claudemd.ts` 明确记载：`"The memory says X exists" is not the same as "X exists now."`
  - 记忆是只写或滞后更新的静态文本快照，而真实文件系统与代码处于持续变动中。
- **规约**：
  - **验证优先于声明物理法则**：记忆库命中信息只能作为“探索线索 (Clue)”，绝对不能作为“免检事实 (Ground-Truth)”；
  - 任何依据记忆执行的写操作或敏感系统调用，前置必须强制调用探针工具（如 `view_file`、`list_dir`、`netstat`）进行物理确认；若物理状态与记忆矛盾，立即以物理状态为准并异步触发记忆修正。

---

## 3. LESSON #363: 深度反向传播中权重谱范数溢出导致梯度断流/爆炸
- **症状**：在深层 Transformer（>50层）中修改残差结构或自定义非线性映射后，底层注意力参数梯度范数逼近 0（梯度弥散），或者在训练前几个 Step 梯度突增触发 `loss=NaN`（梯度爆炸）。
- **根因**：
  - 链式法则本质是跨层雅可比矩阵的连乘：$g_{final} = W_1^\top W_2^\top \dots W_L^\top g_{initial}$；
  - 矩阵的最大奇异值（谱范数 $\|W\|_2$）代表了该变换的最大放大倍率。若各层谱范数平均值为 0.9，50 层后为 $0.9^{50} \approx 0.005$；若平均值为 1.1，50 层后为 $1.1^{50} \approx 117.4$。
- **规约**：
  - 深层网络初始化必须检查权重矩阵谱范数；
  - 优先采用基于 **Sinkhorn-Knopp 双随机归一化** 或正交初始化（Orthogonal Init），确保变换矩阵的谱范数严格守恒于 1.0；
  - 在残差连接路径上，严格控制未经 Norm 约束的裸矩阵叠加。

---

## 4. LESSON #364: 线性联想记忆中 Hebbian 累加饱和与 Delta Rule 误差驱动必要性
- **症状**：在实现长程线性注意力（Linear Attention）或轻量外部 KV 状态缓存时，简单的外积累加机制（$S_t = S_{t-1} + k_t v_t^\top$）在序列变长后出现严重的记忆召回混淆与特征饱和。
- **根因**：
  - 纯 Hebbian 规则缺乏“遗忘”与“纠错”机制。当相同的 Key 模式反复出现时，对应的 Value 向量被无界累加，状态矩阵的秩迅速退化，高幅值旧特征淹没了新特征。
- **规约**：
  - 借鉴 Kimi KDA (Kimi Delta Attention) 架构设计：
    1. **对角衰减门控**：先引入每通道独立的遗忘率 $\bar{S}_t = \operatorname{Diag}(\alpha_t) S_{t-1}$；
    2. **预测误差驱动**：计算当前状态对输入的预测误差 $e_t = v_t - \bar{S}_t^\top k_t$；
    3. **残差受控写入**：仅将误差残差按学习率 $\beta_t$ 写入：$S_t = \bar{S}_t + \beta_t k_t e_t^\top$。
  - 凡构建状态记忆系统，必须具备“已掌握知识零增量写入”的负反馈自限能力。
