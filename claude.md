# 微信公众号自动更新工具

## 项目概览

自动化完成微信公众号内容更新的四个步骤：热点发现 → 素材收集 → AI 写作 → 配图发布。

## 目录结构

```
微信公众号/
├── tools/
│   ├── utils.py                          # 公共工具函数
│   ├── 1_hot_topics/hot_topics.py        # 工具1: 热榜搜索
│   ├── 2_article_search/article_search.py # 工具2: 文章搜索
│   ├── 3_article_writer/article_writer.py # 工具3: AI 写作
│   └── 4_wechat_publisher/wechat_publisher.py # 工具4: 发布
├── data/
│   ├── hot_topics/      # 热点数据 (按日期 YYYY-MM-DD.json)
│   ├── source_articles/ # 原始文章 (按日期/热点ID.json)
│   └── final_articles/  # 生成文章 (按日期/热点ID.json + images/)
├── config/config.yaml   # 配置文件
├── .env                 # 密钥 (不提交 git)
├── .env.example         # 密钥模板
├── main.py              # 主流程入口
└── requirements.txt
```

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置密钥
cp .env.example .env
# 编辑 .env 填入各项 API Key

# 3. 运行完整流程
python main.py

# 4. 分步运行
python main.py --step 1          # 只爬热榜
python main.py --step 2          # 只搜文章
python main.py --step 3          # 只 AI 写作
python main.py --step 4          # 只发布（默认草稿）
python main.py --step 4 --publish # 直接发布
```

## 各工具说明

### 工具1: 热榜搜索 (`tools/1_hot_topics/`)
- 数据源：微博热搜、百度热搜、今日头条热榜、抖音热点
- 筛选：保留榜单前20名，跨平台热点优先
- 输出：`data/hot_topics/YYYY-MM-DD.json`

### 工具2: 文章搜索 (`tools/2_article_search/`)
- 数据源：搜狗微信搜索、百度网页、今日头条、知乎
- 每个热点抓取最多5篇相关文章
- 输出：`data/source_articles/YYYY-MM-DD/{topic_id}.json`

### 工具3: AI 写作 (`tools/3_article_writer/`)
- 使用 Claude API (claude-sonnet-4-6)
- 根据参考文章写出微信公众号风格文章
- 自动生成微信 HTML 排版
- 输出：`data/final_articles/YYYY-MM-DD/{topic_id}.json`

### 工具4: 配图 & 发布 (`tools/4_wechat_publisher/`)
- 用 DALL-E 3 生成封面配图
- 上传素材到微信公众号后台
- 创建图文草稿，支持一键发布
- 输出：更新文章 JSON + `data/final_articles/YYYY-MM-DD/images/`

## 必需的 API Keys

| 变量名 | 用途 | 获取方式 |
|--------|------|----------|
| `ANTHROPIC_API_KEY` | Claude 写文章 | console.anthropic.com |
| `OPENAI_API_KEY` | DALL-E 生成配图 | platform.openai.com |
| `WECHAT_APP_ID` | 公众号发布 | mp.weixin.qq.com → 开发 → 基本配置 |
| `WECHAT_APP_SECRET` | 公众号发布 | 同上 |

## 配置文件 (`config/config.yaml`)

- `hot_topics.top_n`: 每个平台取前N条（默认10）
- `article_search.max_per_topic`: 每个热点最多搜N篇文章（默认5）
- `article_writer.target_length`: 生成文章目标字数（默认1500）
- `publisher.auto_publish`: false=仅创建草稿，true=直接发布
