# 智能阅卷与学情分析

从试卷和参考答案出发，AI 先逐题批改，教师只复核没把握的部分，最后产出班级和个人的学情报告。

当前仓库包含三部分：

- 高考语文论述类文本题库：21 个试卷组、69 道题，已导入 PostgreSQL 的 `Mark` 库。
- 一个教师复核页：`app/static/index.html`、`styles.css`、`app.js`，通过 `/api/demo/dashboard` 读取题库、学生和批改结果。
- 后端：FastAPI + LangGraph + PostgreSQL + DeepSeek + Langfuse，覆盖批改、人工复核、自然语言校准、报告和坏案例分析。

## 技术栈

- Python 3.12
- FastAPI、SQLAlchemy 2.x async、psycopg 3
- LangGraph 1.2.x，Postgres checkpointer
- DeepSeek（OpenAI 兼容接口）
- Langfuse 5.x
- pytest、ruff

## 环境要求

- Python 3.12 和 `.venv`
- Docker 里的 PostgreSQL：容器 `agent_test-postgres`，开发库 `Mark`，测试库 `Mark_test`
- 本地 Langfuse：`http://localhost:3000`
- `.env` 里配置 `API_KEY`、`BASE_URL`、`MODEL_NAME`、`LANGFUSE_*`、`MARK_DATABASE_URL`
- `.env` 已在 `.gitignore` 中，不要提交

## 初始化

```powershell
.venv\Scripts\python.exe -m ensurepip --upgrade
.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 题库：建表、导入 docx、填默认分值
.venv\Scripts\python.exe scripts\import_dataset.py --apply
.venv\Scripts\python.exe scripts\init_db.py
.venv\Scripts\python.exe scripts\init_scores.py

# 可选：生成一个班 10 份模拟答卷
.venv\Scripts\python.exe scripts\seed_synthetic.py --exam-code 2023-新高考Ⅰ卷
```

`init_db.py` 会执行 `db/schema.sql` 并写入 9 个错因分类。`import_dataset.py` 只处理题库，不会动业务表。

测试库：

```powershell
docker exec agent_test-postgres createdb -U postgres Mark_test
```

如果已经存在，命令报错可以忽略。

## 启动

```powershell
.venv\Scripts\python.exe scripts\run_server.py --port 8000
```

Windows 上不要直接用 `python -m uvicorn`：uvicorn 0.54 默认用 ProactorEventLoop，psycopg async 会启动失败。`scripts\run_server.py` 已经指定 SelectorEventLoop，并且不支持 `--reload`。

- 教师复核页：`http://localhost:8000/`，读取 `/api/demo/dashboard`
- OpenAPI 文档：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/health`

生产环境不要用 `--reload`，也不要把服务直接暴露到公网。当前没有登录和权限。

## API 流程

```powershell
# 1. 看试卷
Invoke-RestMethod http://localhost:8000/api/exams

# 2. 创建答卷
$body = @{
  student_id = 1
  answers = @(
    @{ question_id = 1; selected_options = @("C") },
    @{ question_id = 4; answer_text = "只答出第一点" }
  )
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/exams/1/submissions `
  -ContentType "application/json" -Body $body

# 3. 启动批改
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/submissions/1/grade

# 4. 查批改结果和复核队列
Invoke-RestMethod http://localhost:8000/api/grading-runs/1

# 5. 教师复核
$review = @{
  corrections = @(
    @{ result_id = 1; final_score = 5; instruction = "第三点同义表达给分" }
  )
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/grading-runs/1/review `
  -ContentType "application/json" -Body $review

# 6. 自然语言校准，可选全量重批
$calibrate = @{
  question_id = 4
  instruction = "第三点只要提到倾向性标题就给分"
  re_grade_all = $false
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/exams/1/calibrate `
  -ContentType "application/json" -Body $calibrate

# 7. 报告
Invoke-RestMethod "http://localhost:8000/api/classes/1/report?exam_id=1"
Invoke-RestMethod "http://localhost:8000/api/students/1/report?exam_id=1"

# 8. 坏案例
Invoke-RestMethod "http://localhost:8000/api/dev/bad-cases?exam_id=1"
```

主要接口：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/exams` | 试卷列表 |
| GET | `/api/exams/{id}` | 试卷、材料、题目、当前细则 |
| POST | `/api/exams/{id}/submissions` | 创建答卷 |
| GET | `/api/submissions/{id}` | 答卷和答案 |
| POST | `/api/submissions/{id}/grade` | 启动批改 |
| GET | `/api/grading-runs/{id}` | 批改状态和逐题结果 |
| POST | `/api/grading-runs/{id}/review` | 教师复核 |
| POST | `/api/exams/{id}/calibrate` | 自然语言校准 |
| GET | `/api/questions/{id}/rubrics` | 细则版本列表 |
| GET | `/api/classes/{id}/report?exam_id=` | 班级报告 |
| GET | `/api/students/{id}/report?exam_id=` | 学生报告 |
| GET | `/api/demo/dashboard?exam_code=` | 教师复核页数据 |
| POST | `/api/dev/seed-synthetic` | 生成模拟班级和答卷 |
| GET | `/api/dev/bad-cases?exam_id=` | 低置信度和教师改分案例 |

## 测试和评测

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe scripts\evaluate.py --fake
```

- 单元测试和集成测试使用 `Mark_test`，LLM 用假客户端，不调用真实 API。
- `scripts/evaluate.py --fake` 用黄金样本的期望分跑指标，验证脚本本身。
- `scripts/evaluate.py` 不带 `--fake` 会调真实模型，产生 API 费用。

## 数据模型

- `exams`、`passages`、`questions`：题库。
- `classes`、`students`、`submissions`、`student_answers`：班级、学生、答卷。
- `rubrics`：评分细则版本，同一题只有一个 `active=true`。
- `grading_runs`、`grading_results`：批改运行和逐题结果。
- `teacher_corrections`：教师修正，数据飞轮的原始记录。
- `calibration_logs`：自然语言校准记录。
- `error_categories`：九个错因分类。
- `reports`：班级和学生报告快照。

同一份答卷可以有多个批改运行。submission、报告和接口的当前结果取最新 `status='completed'` 的运行，历史运行保留用于对比。

## 已知限制

- 不做 OCR、扫描件和手写识别，只处理文本答案。
- 不做 LoRA 微调和 vLLM 部署，本机没有 GPU。
- 没有登录、权限和多租户，只能本地使用。
- 后台任务用 FastAPI `BackgroundTasks`，进程重启会丢；`awaiting_review` 的 LangGraph checkpoint 可以恢复。
- 题库没有官方逐题分值，当前默认选择题 3 分、主观题 6 分。
- 模拟答卷和黄金样本只能验证链路和格式，不能证明真实场景的 95.6% 一致率或 97.1% 免改率。
- `.env` 里的本地数据库密码按机器配置，换机器需要重新填。
- 页面上的“开始批改”会调用 DeepSeek；`.env` 里没有有效 `API_KEY` 时，批改会以 401 失败。
