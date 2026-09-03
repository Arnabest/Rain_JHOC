# JHOC Multi-Tier Memory Taxonomy Catalog

- Generated At: `2026-09-02T16:34:53.842533+00:00`
- Total Memory Records Categorized: `3205`

## 1. Memory Tier Breakdown (L1 / L2 / L3)

| Tier | Level Name | Count | Purpose |
|:---:|---|---:|---|
| **L1** | Hot Context Memory | 16 | 运行时热上下文、当前 JHOC 迁移与操作者交互会话 |
| **L2** | Distilled Architectural Memory | 1092 | 精炼的架构原则、代理排障运行手册与跨模型规范 |
| **L3** | Cold Archive Memory | 2097 | 全量历史 Verse 对话实录与 QQMusicOverlay 遗留资产 |

## 2. Functional Domain Distribution

| Domain Topic | Record Count | Proportion |
|---|---:|---:|
| `Architecture & Infrastructure` | 1933 | 60.3% |
| `Multi-Model & Provider Interop` | 630 | 19.7% |
| `Desktop Agent & UI Automation` | 259 | 8.1% |
| `Legacy Media & Audio Overlay` | 182 | 5.7% |
| `Memory & State Governance` | 111 | 3.5% |
| `Network & Proxy Routing` | 90 | 2.8% |

## 3. Tier × Domain Matrix

| Domain | L1 (Hot) | L2 (Distilled) | L3 (Cold Archive) | Total |
|---|---:|---:|---:|---:|
| `Architecture & Infrastructure` | 2 | 688 | 1243 | 1933 |
| `Desktop Agent & UI Automation` | 0 | 88 | 171 | 259 |
| `Legacy Media & Audio Overlay` | 0 | 16 | 166 | 182 |
| `Memory & State Governance` | 0 | 40 | 71 | 111 |
| `Multi-Model & Provider Interop` | 14 | 226 | 390 | 630 |
| `Network & Proxy Routing` | 0 | 34 | 56 | 90 |

## 4. Query & Lookup Optimization

- **L1 优先注入**：在对话启动时默认加载 L1 热上下文；
- **L2 按需召回**：当意图涉及架构决策、网络代理配置或多模型分发时，精准召回对应 L2 精炼条目；
- **L3 隔离归档**：历史全量归档仅在进行深度溯源和审计时通过图谱节点索引调阅，杜绝长尾干扰。
