# Issue tracker：本地 Markdown

本仓库的 issue 与规格（spec）都是 `.scratch/` 下的 markdown 文件，不使用 GitHub Issues
（远程 `origin` 虽然指向 GitHub，但工单不往那边放）。

## 目录约定

- 一个功能一个目录：`.scratch/<feature-slug>/`
- 规格文件：`.scratch/<feature-slug>/spec.md`
- 实现类工单：一张单一个文件，`.scratch/<feature-slug>/issues/<NN>-<slug>.md`，从 `01` 开始编号；
  不要把多张工单塞进同一个文件
- 每张工单文件靠近顶部写一行 `Status:` 记录当前状态
- 讨论与追加信息写在文件末尾的 `## Comments` 小节下

## 技能要求「发布到 issue tracker」时

在 `.scratch/<feature-slug>/` 下新建文件（目录不存在就创建）。

## 技能要求「取出对应工单」时

读取对应路径的文件；用户通常会直接给出路径或工单编号。

## Wayfinding 操作

> 这一段描述的是「wayfinder 类技能」需要的文件布局；仓库里目前没有自带的 wayfinder 技能实现，
> 所以它是约定而非现成工具。哪天要按这个流程走，照下面的布局手工建文件即可。

map 是一个文件，每张工单对应一个子文件。

- **Map**：`.scratch/<effort>/map.md`（写 Notes / Decisions-so-far / Fog 正文）
- **子工单**：`.scratch/<effort>/issues/NN-<slug>.md`，从 `01` 开始编号，正文写问题本身；
  `Type:` 行记录类型（`research` / `prototype` / `grilling` / `task`），`Status:` 行记录
  `claimed` / `resolved`
- **阻塞**：顶部一行 `Blocked by: NN, NN`；它列出的文件全部 `resolved` 后本单才解除阻塞
- **可做队列（frontier）**：扫描 `.scratch/<effort>/issues/`，取「未关闭、未阻塞、未认领」的文件，
  编号小的优先
- **认领（claim）**：动手前先写 `Status: claimed` 并保存
- **解决（resolve）**：在 `## Answer` 标题下追加答案，置 `Status: resolved`，
  再把「要点 + 链接」追加到 `map.md` 的 Decisions-so-far
