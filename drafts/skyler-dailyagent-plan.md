<!-- 角色日常生活(DailyAgent)完整方案 · 给用户审阅。
     这是「整体方案」,MVP 切口按用户要求留到后面单独细化(见 §10 占位)。
     代码锚点(表结构 / 现有链路)标「待 CC 核」,落地前先走只读调查(§9)。
     DailyAgent = 「角色机制」Brick 2,父设计见 character-mechanism-seed.md。 -->

# Skyler · 角色日常生活(DailyAgent)完整方案

## 0. 目标(已对齐)

给 Skyler 的角色一个**可信、连续的内在生活**:她**自主过着自己的一天** —— 有一套符合性格、从昨天延续的作息,这份生活渗进她怎么说话、何时主动找你、以及她的心情;而不是每条消息临场重编"我在干嘛"的无状态聊天框。

这是「角色机制」的 **Brick 2(DailyAgent)** —— 给角色一个模型每轮读得到的持久自我。

**已确认边界:** 自主(非用户排程工具)· 排程优先(欲望驱动作后续增强)· 单角色 Mai · 跟真实墙钟走 · **连贯是核心要求**。

---

## 1. 设计原则

1. **轻量** —— 不跑 Smallville 那种**高频逐-tick**(每 10 秒一轮)循环(烧钱根源)。基线 = 每天生成一次 + 便宜 ticker 推进 + 按需 react;**低频异步心跳**(每 30–60 分,v1+,见 §6.5)是可选加法,仍比 Smallville 便宜约 100×。"不跑逐-tick" ≠ "后台零 LLM",是"别跑高频循环"。
2. **连贯四面**(全部一等公民):①一天之内 ②跨天 ③与人格 ④与状态。每面有对应机制(见 §5)。
3. **从现有砖搭** —— `current_activity` / APScheduler / `profile_summary` / proactive / `<state_update>` / `<emotion>` 导演,不从零造。
4. **真实时间** —— 她的"一天"= 你的墙钟。

---

## 2. 参考架构(调研)

### 学界

- **Stanford Generative Agents(Smallville)** —— 自顶向下日程(粗→小时→细)是**连贯之源**;memory + reflection 给跨天连续。但**逐-tick 调 LLM**(每 game step),25 agent × 2 天烧上千美元 → 贵的部分正是我们要避开的。
- **Lyfe Agents** —— 三招把成本砍到 1/10~1/100:**option-commit**(承诺一个"option"一段时间,不每步重决策)、异步自我监控、**Summarize-and-Forget 记忆**。→ 我们的"日程 = 承诺的 option,逐 tick 退化成查表"直接源于此。
- **Affordable Generative Agents(AGA)** —— Lifestyle Policy(用缓存策略替代重复 LLM 推理)+ Social Memory(压缩重复对话)。同等可信、大幅降本。
- **D2A(ICLR 2025,Desire-driven Autonomy)** —— **单 agent**,用动态价值系统(需求理论:社交 / 自我实现 / 自我照顾)让 LLM 自主提出并选活动;每步评估状态→提候选→选最满足内在动机者。生成的日常比 ReAct/BabyAGI 更自然连贯。→ 我们的**「欲望驱动」增强层(§6)**就借它。

### 产品

- **Personal Human(AI 生活模拟)** —— 最贴愿景:角色不是聊天框,而是有自己节奏 / 心情 / 成形的自我,会画画 / 做饭 / 运动 / 读书 / 发展爱好、有自发行为,每个行为反映性格与长期目标。**= 我们要做的同款方向。**
- **主流陪伴(Nomi / Replika / Kindroid / Character AI / Anima…)** —— 大多只有**主动消息 + 记忆 + mood-aware 回复**,**没有真自主日常**。→ 自主日常是 Skyler 的差异化,且踩在前沿方向上。

---

## 3. 架构(完整系统)

六个步骤:

```
每天 0:00 / 首次启动
 └─[生成] persona + 昨日总结(profile_summary + 昨天日程)+ 今日日历/天气 (+需求向量 v1)
       → 一次 LLM → 今日日程(5-8 块:时段 + 活动 + 一句心境)→ 存表

运行中(墙钟驱动)
 └─[ticker] APScheduler interval(每 N 分)
       → 查当前时段 → 写 character_states.current_activity (+派生 mood/energy · v1)
       → 纯查表,0 LLM

她说话 / 主动时
 ├─[读回·Brick1] current_activity(+mood)注入对话 system prompt   ★命门
 ├─① 对话引用("刚在画画")
 ├─② 主动消息反映当前活动 / 日程块触发(睡前块 → 晚安)
 └─③ mood + Live2D 表情/动作(接现有 <emotion> 三通道导演)

真事件(你说"一起玩" / 计划变)
 └─[react/replan] LLM 看"当前块=X" → 反应 or 改后半天        ← 弹性在此

日终
 └─[reflection] 总结今天(她的活动 + 你俩干了啥)→ 喂明天生成   → 跨天连贯
```

**数据层(待 CC 核):** 今日日程(新表 or 扩 `character_states`)· 当日 reflection · (v1)需求向量。

---

## 4. 渠道:日常在哪儿被"看见"(完整 ①②③)

- **① 对话** —— `current_activity` 进 prompt,她说话时引用("我刚在画画")。
- **② 主动消息** —— proactive 反映当前活动("画完了,歇会儿~"),且日程块本身可作 proactive 触发源(睡前块 → 晚安)。
- **③ mood + Live2D** —— 活动 → 派生心情(忙了一天 → 有点累)→ 影响语气 + Live2D 表情/动作。接已有 `<emotion>` 三通道导演,不另起炉灶。

> 完整方案三条全有;MVP 切多少留 §10。

---

## 5. 连贯怎么保证(逐面 → 机制)

| 连贯面 | 怎么保证 |
|---|---|
| **一天之内**(活动成弧、不跳戏、合时段) | **一次性生成整天**日程(LLM 看得到整条弧),而非每块独立选 |
| **跨天**(今天接昨天、她"记得") | 把**昨日总结**(`profile_summary` + 昨天日程)喂进今天生成;日终 reflection 作桥 |
| **与人格**(做的事符合她是谁) | 把 **persona** 喂进生成 |
| **与状态/对话**(嘴上说的 == `current_activity` == 当前块) | **单一真源**:日程 → 写 `current_activity` → prompt 读它,三者不打架 |

**验收含义:** 一天内的连贯一眼可见;**跨天连贯得真跨天才看得出** → 真机验收(尤其多天)是唯一验收门,几小时验不了 —— 这也是它适合放视频后做扎实的原因。

---

## 6. 欲望驱动增强(v1+ · 借 D2A)

排程跑通后的进阶层:给角色一个**需求向量**(陪伴 / 创作 / 休息 / 自我照顾),日程生成由 need 偏置选活动,need 随时间消长。→ 比静态日程更有机的变化 + 更强人格对齐("她自己想做",而非"排好了")。**叠在排程之上,非替代。** MVP 不上。

---

## 6.5 自主心跳(异步 · v1+ 活着层)

纯确定性 ticker 的风险是像**自动钢琴卷** —— 一天在 0 点排死,中途不自发产生"新"事(除非你触发)。加一个**低频异步后台心跳**(每 30–60 分一次廉价 LLM 调用),让她在你不在时也能:冒个念头 / 据这天过得怎样微调在做什么 / 心情漂移 / 偶尔做计划外的事。对**陪伴**产品,这种"活着感"是核心卖点(源自 Lyfe Agents 的异步自我监控)。

**影响评估:**
- **成本** —— 不大。醒着约 16h × 每 30–60 分 = 每天约 16–32 次小调用(只看当前状态 + 日程,输出小更新),配便宜模型几分钱/天,仍比 Smallville 便宜约 100×。
- **可信度** —— 正向且明显(player piano vs 活人)。
- **复杂度** —— **真正的代价在此**:后台心跳与用户互动**同时写状态** → 并发 / stomp、无人盯着的 LLM 漂移、验收更难。

**必须有界**(否则又贵又飘):低频(30–60 分)+ 便宜模型 + **只做小幅在途更新**(微调当前活动 / 冒念头 / 调心情,**非**每次全量重排)+ 只在醒着时段 + 写状态串行化。

**架构归宿:** 这个后台心跳 = AIRI 认知架构的 **conscious / System-2 慢循环**,也是 **Brick 3(真 FSM / 状态演化)** 的落点 —— 与「角色机制」大图一致。**不进 MVP**,v1+ 加。

---

## 7. 跟「角色机制」的关系(brick path)

- **Brick 1 · 状态真读回**(`current_activity`/mood 注入生成)= **地基 / 前置**。没它,这套日常对对话**隐形**。
- **Brick 2 · DailyAgent** = 本方案(生成 + 推进 + react + reflect)。
- **Brick 3 · 状态加规则 / 真 FSM** = mood/energy 衰减转移(接渠道 ③)。
- **Brick 4 · 上下文仲裁** = react/replan + 把状态 + 输入调和成反应。

→ DailyAgent 是**脊柱**,Brick 1/3/4 挂在它上面。所以做 Brick 2 必然带出 Brick 1(前置)、并为 3/4 铺路。

---

## 8. 成本(为什么这叫"轻量")

每天 ~1 次 LLM(生成)+ ~1 次(日终 reflection)+ react 只在**你主动互动时**(本来就会发生)。对比 Smallville 每天上千次调用 —— **可忽略**。单角色、无空间环境,比 D2A/Lyfe 这些研究框架还省。

---

## 9. 复用的砖 + 落地前的只读调查门

**现有砖:** `character_states.current_activity`/`mood` · APScheduler(已跑起床/饭点/睡前 proactive)· `profile_summary` + 滚动摘要 · proactive 链路 · `<state_update>` · 日历(EventKit/Google)· 天气(amap)· `<emotion>` 导演。

**调查门(只读,grounding 后才 spec-lock):**

```
【DailyAgent · 只读调查 · CC 读代码报告 · 0 改动】
grep / 读代码,逐条回报「文件路径 + 关键片段 + 一句话结论」:
1. ★character_states 表 —— 列结构;current_activity / mood 怎么写(<state_update> 链路 + 有无其它写入点)、
   **怎么读** —— 有没有真注入进 ChatAgent 的 system prompt?还是只前端显示?(= Brick 1 现状,最关键)
2. APScheduler —— 现有 job 怎么注册(cron/interval);起床/饭点/睡前 proactive 的 trigger 在哪个文件、长啥样。
3. proactive 链路 —— proactive 怎么取 current_activity / mood?在哪拼 prompt?
4. profile_summary / 昨日总结 —— 怎么生成、存哪、何时更新;滚动摘要在哪。
5. 日历 / 天气读接口 —— EventKit/Google + amap 天气的读取签名,生成日程时能否取"今天的安排 / 天气"。
6. 有无任何已存在的 schedule / routine / daily / activity 相关表 / 字段 / 代码(避免重复造)。
不写代码、不改文件;有疑义先问。
```

---

## 10. MVP 切口(占位 · 后面单独细化)

> 按你的安排,MVP 留到完整方案定稿后再切。**自然缝**预记于此:
> **[生成] + [ticker 推进] + [Brick 1 读回] + 渠道 ①②** = MVP 候选;
> **③(mood/Live2D)、欲望驱动、react/replan、reflection 跨天** = 留 v1。
> 理由:这缝最小、能独立真机验(看 `current_activity` 是否随时间推进且符合人格),
> 且立刻让"她有自己的一天"在 demo 里读得出。细化待定。
