---
name: "wechat-content-pipeline"
description: "运行微信公众号前3步内容生产流程。用户要求抓热点、搜素材、生成公众号文章，或明确要执行步骤1/2/3时调用。"
---

# WeChat Content Pipeline

用于执行微信公众号项目的前 3 个步骤：

1. 热榜搜索与筛选
2. 文章搜索与素材收集
3. AI 写作生成公众号文章

当用户出现以下意图时调用本 Skill：

- 想一键跑完选题、搜文、写作
- 提到“执行前 3 步”
- 想批量生成当天公众号候选文章
- 想指定日期或指定热点生成文章

## 运行前检查

在开始前先确认：

- 当前工作目录是项目根目录
- `.env` 已配置可用的 `DEEPSEEK_API_KEY`
- 依赖已安装

如用户没有特别说明，默认运行：

```bash
python main.py --step 1 2 3
```

## 常用命令

完整执行前 3 步：

```bash
python main.py --step 1 2 3
```

指定日期执行前 3 步：

```bash
python main.py --step 1 2 3 --date YYYY-MM-DD
```

只执行写作，且只处理指定热点：

```bash
python main.py --step 3 --date YYYY-MM-DD --topic-id <topic_id>
```

步骤 1 需要控制每个平台抓取数量时：

```bash
python main.py --step 1 2 3 --top 10
```

## 执行流程

1. 先读取 `main.py` 或相关工具，确认参数仍与 Skill 一致。
2. 根据用户是否指定 `date`、`top`、`topic-id` 组装命令。
3. 运行前 3 步主流程。
4. 关注终端输出是否出现：
   - 未获取到热点
   - 搜文失败
   - 写作失败
   - 未设置环境变量
5. 如执行成功，检查以下输出目录是否产生新结果：
   - `data/hot_topics/`
   - `data/source_articles/`
   - `data/final_articles/`

## 结果汇报

完成后向用户简要说明：

- 实际执行了哪些步骤
- 使用的日期、热点数量或热点 ID
- 生成了多少个热点、多少份素材、多少篇文章
- 若有失败，指出失败阶段和错误摘要

## 注意事项

- 除非用户明确要求，否则不要自动执行步骤 4。
- 如果只需要补写文章，可跳过步骤 1 和步骤 2，仅运行步骤 3。
- 若用户要求“重新生成某个热点文章”，优先使用 `--topic-id` 精确处理。
