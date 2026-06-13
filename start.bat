@echo off
echo ========================================
echo 客户主数据变更管理系统 - 启动脚本
echo ========================================
echo.

echo [1/3] 检查Python环境...
python --version
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python 3.8+
    pause
    exit /b 1
)

echo.
echo [2/3] 初始化数据库和示例数据...
python scripts/init_data.py

echo.
echo [3/3] 启动API服务...
echo 服务地址: http://127.0.0.1:8000
echo API文档: http://127.0.0.1:8000/docs
echo.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

pause
