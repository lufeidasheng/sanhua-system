import sys
import os
import libcst as cst
import libcst.matchers as m

LOG_METHODS = {"debug", "info", "warning", "error", "critical"}

class LoggerCallTransformer(cst.CSTTransformer):
    def __init__(self):
        super().__init__()
        self.modified = False

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
        # 识别 self.logger.xxx(...)
        if m.matches(
            original_node.func,
            m.Attribute(
                value=m.Attribute(
                    value=m.Name("self"),
                    attr=m.Name("logger")
                ),
                attr=m.Name()
            )
        ):
            method_name = original_node.func.attr.value
            if method_name in LOG_METHODS:
                # 查找 extra 参数
                args = list(updated_node.args)
                new_args = []
                changed = False
                for arg in args:
                    if arg.keyword and arg.keyword.value == "extra":
                        # 这里可以做你想的修改，比如替换 extra 的内容
                        # 也可以检查格式，或者删掉不符合规范的 extra 参数
                        # 下面示例仅简单打印并保留
                        print(f"Found extra param in {method_name} at line {original_node.func.lineno}")
                        # 你可以改写 arg.value 这里示范保留
                        new_args.append(arg)
                    else:
                        new_args.append(arg)

                if changed:
                    self.modified = True
                    return updated_node.with_changes(args=new_args)
        return updated_node

def walk_files(root_dir: str):
    for dirpath, _, filenames in os.walk(root_dir):
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)

def main(root_dir):
    for filepath in walk_files(root_dir):
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()

        tree = cst.parse_module(source)
        transformer = LoggerCallTransformer()
        modified_tree = tree.visit(transformer)

        if transformer.modified:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(modified_tree.code)
            print(f"Modified {filepath}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fix_logger_calls.py /path/to/code")
        sys.exit(1)
    main(sys.argv[1])
