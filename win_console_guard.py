# -*- coding: utf-8 -*-
"""
win_console_guard.py — Windows 控制台 ANSI 翻译层护栏
=====================================================
【背景】tqdm 在 Windows 上导入时会调用 colorama.init() 包装 stdout/stderr，
       把进度条里的 ANSI 转义码（光标上移 \x1b[A 等）翻译成 Win32 控制台调用。
【缺陷】部分控制台环境下（服务器面板/无控制台句柄/VT 模式异常/旧版 colorama
       懒初始化）会出现"需要翻译但 winterm 未初始化(None)"的矛盾状态：
       颜色码被静默跳过，光标码则抛出
       AttributeError: 'NoneType' object has no attribute 'cursor_adjust'
       ——即 Web 端"本地记忆不可用"间歇性报错的根因。是否触发取决于当时
       控制台会话的状态，所以重启后常常又自愈，表现为"时好时坏"。
【方案】模型加载前调用 ensure_safe_console()：发现 winterm 缺失时注入一个
       全部吞掉的安全实现，把崩溃点堵死。幂等、线程安全；健康环境下
       零干预、零开销（进度条光标操作被忽略，仅影响显示，不影响功能）。
"""

import sys
import threading

_done = False
_lock = threading.Lock()


class _NoopWinTerm:
    """winterm 缺失时的兜底实现：吞掉全部 Win32 调用"""

    def reset_all(self, *a, **k):
        pass

    def style(self, *a, **k):
        pass

    def fore(self, *a, **k):
        pass

    def back(self, *a, **k):
        pass

    def set_console(self, *a, **k):
        pass

    def set_cursor_position(self, *a, **k):
        pass

    def cursor_adjust(self, *a, **k):
        pass

    def erase_screen(self, *a, **k):
        pass

    def erase_line(self, *a, **k):
        pass

    def set_title(self, *a, **k):
        pass


def ensure_safe_console():
    """堵住 colorama winterm=None 的间歇性崩溃点（幂等；任何平台调用都安全）"""
    global _done
    if _done:
        return
    with _lock:
        if _done:
            return
        try:
            import colorama.ansitowin32 as _a2w
        except Exception:
            _done = True
            return  # colorama 缺失或自身损坏：无此问题
        _done = True
        if getattr(_a2w, "winterm", None) is not None:
            return  # 环境健康：不干预
        _a2w.winterm = _NoopWinTerm()
        if sys.platform == "win32":
            # Windows 下 winterm=None 属异常态（无控制台/VT异常），记录便于排查
            try:
                import colorama
                _ver = getattr(colorama, "__version__", "?")
            except Exception:
                _ver = "?"
            print(f"[控制台护栏] colorama({_ver}) 的 winterm 未初始化（无控制台/VT异常环境），"
                  f"已注入安全兜底：进度条光标码将被忽略，模型加载不再因此崩溃")
        # 非 Windows 平台 winterm 本就恒为 None（正常态），静默注入兜底即可：
        # 万一旧版 colorama 在该平台错误激活了转换路径，此处注入同样能防崩溃
