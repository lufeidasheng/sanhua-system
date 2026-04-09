import os
import threading
import logging
import platform
import shutil
import psutil
import datetime
import webbrowser
import requests

logger = logging.getLogger("ActionHandlers")

def get_system_info(core, query):
    """获取系统信息"""
    info = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu": psutil.cpu_percent(),
        "mem": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage('/').percent,
        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    msg = f"🖥️ 系统: {info['os']}\nPython: {info['python']}\nCPU: {info['cpu']}%\n内存: {info['mem']}%\n磁盘: {info['disk']}%\n时间: {info['time']}"
    return {"status": "success", "msg": msg, "info": info}

def open_browser(core, query):
    """打开浏览器（支持URL参数）"""
    url = "https://www.baidu.com"
    if "http" in query:
        url = query.split("http", 1)[-1].strip()
        url = "http" + url
    webbrowser.open(url)
    return {"status": "success", "msg": f"🌐 已打开浏览器: {url}"}

def clear_temp_files(core, query):
    """清理临时文件"""
    tmp_path = "/tmp"
    try:
        shutil.rmtree(tmp_path)
        os.makedirs(tmp_path, exist_ok=True)
        return {"status": "success", "msg": "🧹 临时文件已清理"}
    except Exception as e:
        return {"status": "fail", "msg": f"清理失败: {e}"}

def check_network(core, query):
    """检测网络连通性"""
    try:
        r = requests.get("https://www.baidu.com", timeout=3)
        if r.ok:
            return {"status": "success", "msg": "🌍 网络正常"}
        else:
            return {"status": "fail", "msg": "网络异常"}
    except Exception as e:
        return {"status": "fail", "msg": f"网络检测失败: {e}"}

def screenshot(core, query):
    """截图并保存到桌面"""
    try:
        import pyautogui
        path = os.path.expanduser("~/桌面/screenshot.png")
        img = pyautogui.screenshot()
        img.save(path)
        return {"status": "success", "msg": f"📸 截图已保存到: {path}"}
    except Exception as e:
        return {"status": "fail", "msg": f"截图失败: {e}"}

def say_hello(core, query):
    """AI自我介绍"""
    return {"status": "success", "msg": "你好，我是三花聚顶AI内核，很高兴为你服务！"}

def list_files(core, query):
    """列出当前目录文件"""
    try:
        files = os.listdir(os.getcwd())
        msg = "📁 当前目录文件:\n" + "\n".join(files)
        return {"status": "success", "msg": msg, "files": files}
    except Exception as e:
        return {"status": "fail", "msg": f"读取文件列表失败: {e}"}

def search_file(core, query):
    """搜索文件（支持关键字）"""
    keyword = query.replace("搜索文件", "").strip()
    result = []
    for root, dirs, files in os.walk(os.getcwd()):
        for f in files:
            if keyword in f:
                result.append(os.path.join(root, f))
    if result:
        return {"status": "success", "msg": f"🔎 搜索到 {len(result)} 个文件", "files": result}
    else:
        return {"status": "fail", "msg": "未找到相关文件"}

def send_notification(core, query):
    """发送桌面通知"""
    try:
        msg = query.split("通知", 1)[-1].strip() or "三花聚顶提醒"
        os.system(f'notify-send "{msg}"')
        return {"status": "success", "msg": f"🔔 通知已发送: {msg}"}
    except Exception as e:
        return {"status": "fail", "msg": f"发送通知失败: {e}"}
