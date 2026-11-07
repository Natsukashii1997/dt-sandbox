# dt-sandbox

数字分身 DT-ORC V4.0 的 Multica 沙盒仓库。只放合成内容，用来验证 agent 的执行权限边界（ARCHITECTURE 5.2c）和首跑流程。

- 不放任何真实业务数据、个人信息或凭据。
- `main` 受分支保护：只能经 PR 合并，不能直接推送。
- agent 只推 `agent/…` 分支并开 PR，合并由常浩决定。

## todo-lite

`todo-lite` 是一个只用 Python 3.11 标准库写的极简命令行待办清单（合成首跑项目）。

- 查看版本：`python -m todo_lite --version`（输出 `0.1.0`）
- 跑测试：在仓库根目录执行 `python -m pytest -q`（需先 `pip install pytest`）
