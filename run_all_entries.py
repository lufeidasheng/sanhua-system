import importlib

def run_all_entries():
    mod = importlib.import_module('modules.music_module.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：music_module')
        mod.entry()

    mod = importlib.import_module('modules.language_bridge.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：language_bridge')
        mod.entry()

    mod = importlib.import_module('modules.code_reviewer.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：code_reviewer')
        mod.entry()

    mod = importlib.import_module('modules.aicore_module.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：aicore_module')
        mod.entry()

    mod = importlib.import_module('modules.tts_module.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：tts_module')
        mod.entry()

    mod = importlib.import_module('modules.code_reader.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：code_reader')
        mod.entry()

    mod = importlib.import_module('modules.system_control.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：system_control')
        mod.entry()

    mod = importlib.import_module('modules.self_learning_module.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：self_learning_module')
        mod.entry()

    mod = importlib.import_module('modules.code_inserter.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：code_inserter')
        mod.entry()

    mod = importlib.import_module('modules.virtual_avatar.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：virtual_avatar')
        mod.entry()

    mod = importlib.import_module('modules.voice_ai_core.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：voice_ai_core')
        mod.entry()

    mod = importlib.import_module('modules.format_manager.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：format_manager')
        mod.entry()

    mod = importlib.import_module('modules.douyin_web.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：douyin_web')
        mod.entry()

    mod = importlib.import_module('modules.reply_dispatcher.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：reply_dispatcher')
        mod.entry()

    mod = importlib.import_module('modules.system_monitor.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：system_monitor')
        mod.entry()

    mod = importlib.import_module('modules.voice_input.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：voice_input')
        mod.entry()

    mod = importlib.import_module('modules.desktop_notify.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：desktop_notify')
        mod.entry()

    mod = importlib.import_module('modules.audio_consumer.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：audio_consumer')
        mod.entry()

    mod = importlib.import_module('modules.audio_capture.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：audio_capture')
        mod.entry()

    mod = importlib.import_module('modules.stt_module.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：stt_module')
        mod.entry()

    mod = importlib.import_module('modules.code_executor.module')
    if hasattr(mod, 'entry'):
        print('启动入口模块：code_executor')
        mod.entry()


if __name__ == '__main__':
    run_all_entries()
