# ReqSysAI 改进计划

> 标记 `[x]` 的由 Claude 实现，标记 `[ ]` 的待确认

## Sprint 1: 自动化引擎 + 推送能力（最大 ROI）

- [x] **T1.1 状态自动流转** (2d)
  - 子需求全完成 → 父需求自动流转到 pending_confirm
  - 风险到期未解决 → 自动升级 severity
  - 需求所有 todo 完成 → 需求自动流转
  - 实现方式：db.event.listen 或 after_flush hook

- [ ] **T1.2 定时任务引擎** (3d)
  - 引入 APScheduler
  - 每周一早上自动生成上周周报草稿
  - 每天早上推送今日待办摘要
  - 过期 todo/需求自动标记
  - 已完成 todo 超过 keep_days 自动归档

- [ ] **T1.3 Webhook 通知** (2d)
  - 配置企微/钉钉/邮件 webhook URL（config.yml）
  - 关键事件推送：需求超期、被指派、风险升级、激励审批结果
  - 每日摘要推送：个人待办汇总
  - 后台管理页面配置 webhook

- [x] **T1.4 需求看板视图** (1.5d)
  - Kanban board：待评审 → 待开发 → 开发中 → 测试中 → 已完成
  - 拖拽改状态（复用 todo 拖拽逻辑）
  - 按项目/负责人筛选
  - 泳道模式（按负责人分行）

## Sprint 2: 量化与洞察

- [x] **T2.1 需求交付周期** (1d)
  - Activity 表已记录状态变更时间
  - 计算 lead time（创建→完成）、cycle time（开发→完成）
  - 需求详情页显示耗时分布
  - 项目级平均交付周期趋势图

- [x] **T2.2 预估 vs 实际偏差** (1d)
  - estimate_days vs actual_minutes 对比
  - 人均偏差率、项目级偏差率
  - 图表展示：散点图（预估 vs 实际）
  - 用于校准未来估时

- [ ] **T2.3 团队健康度仪表盘** (2d)
  - 综合指标卡片：准时交付率、人均吞吐、风险收敛速度
  - 周/月趋势折线图
  - 按项目/团队切换
  - 可导出 PDF/图片用于汇报

- [x] **T2.4 个人效能页** (1d)
  - 个人维度：本月完成 todo 数趋势、参与需求数、获得激励次数
  - 专注时间统计（actual_minutes 聚合）
  - 贡献热力图增强（年度视图）
  - 个人 Profile 页嵌入

## Sprint 3: 易用性飞跃

- [x] **T3.1 全局搜索 Cmd+K** (2d)
  - 搜索：需求编号/标题、todo 标题、人名、项目名
  - 前端 modal + 键盘导航
  - 后端 API：SQLite FTS5 全文搜索
  - 搜索结果分类展示，点击直达

- [ ] **T3.2 批量操作** (1d)
  - 需求列表多选 checkbox
  - 批量修改状态/优先级/负责人
  - 批量创建 todo（粘贴多行文本）
  - 确认弹窗防误操作

- [ ] **T3.3 需求评论 @提及** (1.5d)
  - 评论输入框支持 @人名（拼音搜索）
  - @产生通知（纳入 notif_count）
  - 评论中 @姓名 高亮显示
  - 评论支持需求编号自动链接（REQ-001 → 跳转）

- [x] **T3.4 会议纪要一键拆分** (1.5d)
  - 新建 Meeting 模型（项目下挂载）
  - 上传纪要文本/docx
  - AI 一键提取：待办事项、需求、风险、决议
  - 提取结果可一键创建为 todo/需求/风险
  - 历史记录可回溯

## Sprint 4: 架构前置条件

- [x] **T4.1 领域事件系统** (2d)
  - 定义事件：RequirementStatusChanged, TodoCompleted, RiskEscalated
  - 事件总线：简单的 pub/sub（blinker 库）
  - 订阅者：自动流转、通知推送、Activity 记录
  - 解耦 route 和副作用

- [x] **T4.2 搜索基础设施** (1d)
  - SQLite FTS5 虚拟表
  - 增量索引：模型 after_insert/after_update 触发
  - 统一搜索 API：/api/search?q=xxx

- [x] **T4.3 前端渐进增强** (3d)
  - 关键交互 AJAX 化（需求状态变更、todo 操作免刷新）
  - Toast 通知替代 flash + 页面重载
  - [不需要]移动端关键页面优化（首页、todo）

## 代码质量（持续）

- [x] 提取 constants.py 消灭 magic strings
- [x] 提取 utils/upload.py 消灭重复代码
- [x] 整理所有 routes.py 的 imports 到模块顶部
- [ ] **统一 JSON API 响应格式** (0.5d)
- [z] **添加 type hints 到 service 层** (1d)
- [z] **project/routes.py 和 requirement/routes.py import 整理** (0.5d)

---

**总预估：~27 人天**
- Sprint 1: 8.5d
- Sprint 2: 5d
- Sprint 3: 6d
- Sprint 4: 6d

**建议执行顺序：** T4.1 → T1.1 → T1.4 → T3.1 → T1.2 → T1.3 → T2.x → T3.x
