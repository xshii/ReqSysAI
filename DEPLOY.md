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

## 更新代码（拷贝覆盖）

1. 备份 `instance/`、`config.local.yml`、`app/static/uploads/`
2. 拷贝新代码覆盖（上述文件不会被覆盖，已在 .gitignore）
3. 执行：
```bash
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt  # 安装新依赖
flask db upgrade  # 数据库迁移
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
