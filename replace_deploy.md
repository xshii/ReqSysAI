# 覆盖部署指南

适用场景：在另一台机器上**覆盖代码但保留数据库**的方式更新服务。

## 操作步骤

### 1. 停止服务

```bash
# Windows
taskkill /f /im python.exe

# Mac/Linux
lsof -ti:5001 | xargs kill -9
```

### 2. 覆盖代码

将最新代码覆盖到项目目录，**不要覆盖以下文件/目录**：

- `instance/` — 数据库文件
- `venv/` — 虚拟环境
- `config.yml` — 本地配置
- `prompts.yml` — AI 提示词（如需更新则覆盖）
- `.env` — 环境变量（如有）

### 3. 激活虚拟环境

```bash
# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate
```

### 4. 安装依赖（如有新增包）

```bash
pip install -r requirements.txt
```

### 5. 数据库迁移

```bash
# 方式一：使用 Alembic 迁移（推荐）
set FLASK_APP=app:create_app
flask db upgrade

# 方式二：如果方式一报错（版本不匹配），使用保底方案
# 仅创建新增的表，不影响已有数据
python -c "from app import create_app; from app.extensions import db; app=create_app(); app.app_context().push(); db.create_all(); print('OK')"
```

> **注意**：`db.create_all()` 只创建不存在的表，不会删除或修改已有表和数据。但它**不会添加新字段到已有表**。如果有新字段（如 `amount_detail`），需要手动执行：
>
> ```bash
> # SQLite 手动添加字段示例
> python -c "
> from app import create_app
> from app.extensions import db
> app = create_app()
> with app.app_context():
>     try:
>         db.session.execute(db.text('ALTER TABLE incentives ADD COLUMN amount_detail VARCHAR(200)'))
>         db.session.commit()
>         print('字段已添加')
>     except Exception as e:
>         print(f'字段可能已存在: {e}')
> "
> ```

### 6. 启动服务

```bash
# Windows
set FLASK_APP=app:create_app
flask run --host 0.0.0.0 --port 5001

# Mac/Linux
FLASK_APP=app:create_app flask run --host 0.0.0.0 --port 5001
```

### 7. 验证

浏览器访问 `http://localhost:5001/`，确认正常。

---

## 本次更新新增的数据库变更

| 变更 | 说明 |
|------|------|
| 新表 `activity_timers` | 活动计时器（`db.create_all()` 自动创建） |
| `incentives.amount_detail` | 多人金额明细字段（需 `ALTER TABLE` 或 `flask db upgrade`） |

## 快速一键脚本（Windows）

```bat
@echo off
cd /d %~dp0
call venv\Scripts\activate
pip install -r requirements.txt
set FLASK_APP=app:create_app
python -c "from app import create_app; from app.extensions import db; app=create_app(); app.app_context().push(); db.create_all(); print('Tables OK')"
python -c "from app import create_app; from app.extensions import db; app=create_app(); ctx=app.app_context(); ctx.push(); [db.session.execute(db.text(s)) for s in ['ALTER TABLE incentives ADD COLUMN amount_detail VARCHAR(200)'] if not print(f'Executing: {s}')]; db.session.commit(); print('Fields OK')" 2>nul
flask run --host 0.0.0.0 --port 5001
```
