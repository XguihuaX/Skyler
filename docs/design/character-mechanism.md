# 角色机制 · 设计种子(待展开)

> **设计种子 · 待展开**:这是 parked 的种子文档,不是成品。先把整体框架立住,完整 brick spec / 接口 / 验收门留后续展开。
> 回链:[ROADMAP · 核心专项「角色机制(角色判断状态机)」](../../ROADMAP.md#核心专项角色机制角色判断状态机) · 父项 brick 1-4 落点。

**统一线**:给角色一个持久、有结构的"自我",让模型每轮去**读**,而不是每轮重新发明自己。
`persona + state/fsm + dailyagent + 仲裁` = 一套东西的 4 层,合称「角色机制」(= 项目头号差异化)。

## 四层

1. **Persona —— 她是谁(稳定底座)**。身份/性格/语气/禁忌,慢变。现状:有,只 Mai 完整。
2. **State / 真 FSM —— 她现在如何(持久动态)**。心情/亲密度/精力/当前活动/最近想法。真 FSM 三要件:(a) 持久 (b) 按规则演化(衰减/转移/触发) (c) **读回 prompt 影响生成**。**这层现在弱 = 花架子**(LLM 随手写 + 显示,无规则、无读回)。做真 = 整套核心。
3. **DailyAgent —— 她在过怎样的一天(状态生产者)**。每天生成连贯日程 → 驱动 current_activity 随时间走;扎根 persona + 昨天 + 外部(日历/天气/时间)。把 current_activity 从 ad-hoc 变 coherent。
4. **上下文仲裁 —— 怎么变成反应(指挥)**。响应时把 ①②③ + 用户输入 + 屏幕感知 调和成当下反应。没它 state 只是数据;有它 state 才驱动行为。最难,最后做。

## emergent build path(不 big-bang,每块基于已有砖)

- **Brick 1** 让 State 真"读回" —— mood + current_activity 进 system prompt、真影响生成。最便宜,把花架子变真第一步。
- **Brick 2** DailyAgent 最小切片 —— 每天一次生成日程 → ticker 驱动 current_activity。= demo 切片("她有自己的一天")。完整方案见 [dailyagent-plan.md](./dailyagent-plan.md)。
- **Brick 3** State 加规则 —— mood/energy 衰减/转移(现在大概只有 intimacy decay),让它真是 FSM。
- **Brick 4** 上下文仲裁 —— 最后做。

## 大图

三条轴:**输入/感知**(UIA、活动感知)· **自我/状态**(本机制)· **输出/表达**(`<emotion>` 三通道导演)。角色机制 = 夹在感知与表达之间的"自我"。AIRI 认知架构(perception→reflex→conscious→action)的落点。

## 待办(后续)

1. 只读 dump `character_states` 现状:current_activity/mood 读回 prompt 没?有无规则演化?proactive 怎么消费?→ 决定 Brick 1 是"补"还是"从头",也决定 README #3 能说多满。
2. 把本种子展开成完整设计文档(大框架 + 四层 + brick spec + 接口契约 + 验收门)。本身是 PM 作品集料。

时间线:**设计现在做**(便宜、是差异化、是作品集);**full build = post-video**;demo 用 Brick 1+2 切片。
