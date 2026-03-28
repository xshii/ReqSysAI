# 内网部署指南

## 文件结构

```
ReqSysAI/
├── config.yml              # 默认配置（随代码更新）
├── config.local.yml        # 本地覆盖配置（不被代码覆盖）
├── instance/               # 数据库（不被代码覆盖）
│   └── reqsys.db
├── app/static/uploads/     # 用户上传文件（不被代码覆盖）
├── venv/                   # 虚拟环境（不被代码覆盖）
└── ...                     # 代码文件
```

## 首次部署

```bash
# Windows
scripts\init_windows.bat

# macOS/Linux
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python scripts/init_db.py
flask db stamp head
```

## 更新代码（覆盖代码，保留数据）

以下文件/目录包含用户数据，**拷贝代码时不要覆盖**：
- `instance/reqsys.db` — 数据库
- `config.local.yml` — 本地配置
- `app/static/uploads/` — 上传文件
- `venv/` — 虚拟环境

### 标准流程

```bash
# 1. 停止服务
kill $(lsof -ti:5001) 2>/dev/null   # macOS/Linux
# Windows: 关闭运行中的终端

# 2. 拷贝新代码覆盖旧代码（跳过上述数据文件）

# 3. 激活虚拟环境
source venv/bin/activate            # macOS/Linux
# Windows: venv\Scripts\activate

# 4. 安装新依赖（如有）
pip install -r requirements.txt

# 5. 执行数据库迁移
export FLASK_APP=app:create_app     # macOS/Linux
# Windows: set FLASK_APP=app:create_app
flask db upgrade

# 6. 重启服务
flask run --host 0.0.0.0 --port 5001
```

### 迁移失败处理

如果 `flask db upgrade` 报错（常见于跨多版本更新），用以下 SQL 手动补齐字段，然后 `flask db stamp head` 跳过迁移。

### 最新数据库变更记录

将以下内容保存为 `scripts/manual_migrate.py`，执行 `python scripts/manual_migrate.py` 即可补齐所有字段和表：

```bash
source venv/bin/activate
python scripts/manual_migrate.py
```

### 查看迁移状态

```bash
flask db current    # 当前数据库版本
flask db history    # 迁移历史
flask db heads      # 最新迁移版本
```

### 强制跳过迁移（数据库已手动更新）

```bash
flask db stamp head   # 标记为最新，跳过所有未执行的迁移
```

## 自定义配置

复制 `config.local.yml.example` 为 `config.local.yml`，修改需要的配置项。
`config.local.yml` 会覆盖 `config.yml` 中的同名配置。

常用配置项：
- `app.secret_key`: 生产环境必须修改
- `app.port`: 监听端口（默认5001）
- `admin.employee_id`: 管理员工号
- `ollama.base_url`: AI 服务地址
- `ollama.model`: AI 模型名

## 启动

```bash
# Windows
scripts\run_windows.bat

# macOS/Linux
source venv/bin/activate
flask run --host 0.0.0.0 --port 5001
```
