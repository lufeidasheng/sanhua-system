# fix_package_exports.sh
for pkg in code_reader code_inserter code_reviewer code_executor format_manager
do
  init="modules/$pkg/__init__.py"
  main_py=$(ls modules/$pkg | grep -E "${pkg}\.py$")
  class_name=$(echo "$pkg" | sed -r 's/(^|_)([a-z])/\U\2/g')  # 下划线 → 驼峰
  cat > "$init" <<EOF
from .${main_py%.py} import ${class_name}
__all__ = ["${class_name}"]
EOF
  echo "✔ 导出 $class_name 到 $init"
done
