#!/usr/bin/env python3
"""NEW6 - AI武侠互动小说 启动入口"""
import os
import sys

# 确保工作目录是脚本所在目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from web_server import app

if __name__ == '__main__':
    print("=" * 50)
    print("  NEW6 - AI武侠互动小说")
    print("  访问地址: http://localhost:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=False)
