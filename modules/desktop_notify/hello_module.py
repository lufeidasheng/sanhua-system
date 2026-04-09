import os
import gi
gi.require_version('Notify', '0.7')
from gi.repository import Notify

def say_hello(name="世界"):
    """Fedora优化的问候函数，支持系统通知"""
    greeting = f"你好，{name}！这是来自Fedora问候模块的祝福。"
    print(greeting)
    
    # GNOME通知集成
    Notify.init("HelloModule")
    notification = Notify.Notification.new(
        "问候通知",
        greeting,
        "dialog-information"
    )
    notification.show()

def register():
    """返回动作注册字典"""
    return {"say_hello": say_hello}

def register_actions(dispatcher):
    """注册动作到系统调度器"""
    dispatcher.register_action(
        key="greet",
        action=say_hello,
        module_name="fedora_greeter.hello_module",
        description="发送个性化问候"
    )
    
    # 注册系统级DBus服务
    dispatcher.register_dbus_service(
        service_name="org.fedoraproject.Greeter",
        object_path="/org/fedoraproject/Greeter"
    )
