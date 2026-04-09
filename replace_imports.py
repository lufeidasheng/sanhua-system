import os

root_dir = "/home/lufei/文档/聚核助手2.0"
old_import = "core.core2_0"
new_import = "core.core2_0"

modified_files = []

for subdir, dirs, files in os.walk(root_dir):
    for file in files:
        if file.endswith(".py"):
            path = os.path.join(subdir, file)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if old_import in content:
                content_new = content.replace(old_import, new_import)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content_new)
                modified_files.append(path)

print(f"替换完成。共修改了 {len(modified_files)} 个文件：")
for f in modified_files:
    print(f)
