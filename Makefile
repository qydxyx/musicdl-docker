.PHONY: run stop docker docker-stop binary test clean

# ── 本地开发启动 (macOS / Linux 原生) ──
run:
	bash run.sh start

stop:
	bash run.sh stop

# ── Docker 容器构建与运行 ──
docker:
	docker compose build && docker compose up -d
	@echo "🌐 musicdl Web UI 已就绪: http://localhost:$${PORT:-8080}"

docker-stop:
	docker compose down

# ── 二进制单文件打包 (基于 PyInstaller) ──
binary:
	pip install -q pyinstaller
	pyinstaller musicdl-web.spec
	@echo "✅ 二进制产物已生成: dist/musicdl-web"

# ── 自动化测试 ──
test:
	pytest tests/ -v

# ── 清理临时文件 ──
clean:
	rm -rf dist/ build/ __pycache__ backend/__pycache__ tests/__pycache__ .pytest_cache *.egg-info
